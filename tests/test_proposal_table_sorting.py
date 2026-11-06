from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import psycopg2
from psycopg2 import sql

from services.api.models import base
from services.api.models.proposal import count_by_status, list_proposals
from services.api.routers.proposals import router
from services.db import get_connection


@pytest.fixture
def proposals():
    marker = "proposal-sort-" + uuid4().hex
    specs = [
        ("Zulu", "skill", "update", "zulu", "pending", 1),
        ("alpha", "rule", "create", "alpha", "pending", 3),
        ("ALPHA", "job", "update", "ALPHA", "approved", 2),
        ("bravo", "hook", "create", "bravo", "pending", 2),
        ("Bravo", "rule", "create", "Bravo", "approved", 1),
        ("Delta", "skill", "update", "delta", "rejected", 4),
    ]
    ids = []
    with get_connection() as conn, conn.cursor() as cur:
        for index, (title, kind, action, target, status, day) in enumerate(specs):
            cur.execute(
                """INSERT INTO improvement_proposals
                (title,target_kind,action,target_name,status,created_at,
                 proposed_item_id,rationale,fingerprint,evidence)
                VALUES(%s,%s,%s,%s,%s,%s,1,'Unchanged rationale',%s,
                 '[{"source":"plan","note":"Full evidence"}]'::jsonb)
                RETURNING id""",
                (
                    title,
                    kind,
                    action,
                    marker + target,
                    status,
                    datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day),
                    f"{marker}-{index}",
                ),
            )
            ids.append(cur.fetchone()[0])
    try:
        yield marker, ids
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM improvement_proposals WHERE id=ANY(%s)", (ids,))


ORDERS = [
    ("title", [1, 2, 3, 4, 5, 0]),
    ("title_desc", [0, 5, 4, 3, 2, 1]),
    ("kind_asc", [3, 2, 1, 4, 0, 5]),
    ("kind_desc", [5, 0, 4, 1, 2, 3]),
    ("action_asc", [1, 3, 4, 0, 2, 5]),
    ("action_desc", [5, 2, 0, 4, 3, 1]),
    ("target_asc", [1, 2, 3, 4, 5, 0]),
    ("target_desc", [0, 5, 4, 3, 2, 1]),
    ("oldest", [0, 4, 2, 3, 1, 5]),
    ("newest", [5, 1, 3, 2, 4, 0]),
]


@pytest.mark.parametrize("sort,positions", ORDERS)
def test_proposal_order_is_global_stable_before_page_without_writes(
    proposals, sort, positions
):
    marker, ids = proposals
    app = FastAPI()
    app.include_router(router, prefix="/proposals")
    client = TestClient(app)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM improvement_proposals WHERE id=ANY(%s) ORDER BY id", (ids,)
        )
        before = cur.fetchall()
    counts = count_by_status()
    pages = [
        client.get(
            "/proposals",
            params={"q": marker, "sort": sort, "limit": 2, "offset": offset},
        )
        for offset in (0, 2, 4)
    ]
    assert all(page.status_code == 200 for page in pages), [p.text for p in pages]
    assert [row["id"] for page in pages for row in page.json()["items"]] == [
        ids[index] for index in positions
    ]
    assert [page.json()["total"] for page in pages] == [6, 6, 6]
    assert list_proposals(q=marker, sort=sort, limit=2, offset=99) == ([], 6)
    assert count_by_status() == counts
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM improvement_proposals WHERE id=ANY(%s) ORDER BY id", (ids,)
        )
        assert cur.fetchall() == before


def test_proposal_header_order_preserves_status_and_search_filters(proposals):
    marker, ids = proposals
    rows, total = list_proposals(
        "pending", q=marker, sort="target_desc", limit=1, offset=1
    )
    assert total == 3 and [row["id"] for row in rows] == [ids[3]]


def test_proposal_title_order_uses_postgres_case_folding_for_non_ascii(proposals):
    marker, ids = proposals
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE improvement_proposals SET title='éClair' WHERE id=%s", (ids[1],)
        )
        cur.execute(
            "UPDATE improvement_proposals SET title='éCLAIR' WHERE id=%s", (ids[0],)
        )
        cur.execute("SELECT lower('éClair'),lower('éCLAIR')")
        assert cur.fetchone() == ("éclair", "éclair")
    rows, total = list_proposals("pending", q=marker, sort="title_desc")
    assert total == 3 and [row["id"] for row in rows[:2]] == [ids[1], ids[0]]


@pytest.mark.parametrize(
    "field", ["title", "target_kind", "action", "target_name", "created_at"]
)
def test_visible_proposal_sort_fields_enforce_nonnull_contract(proposals, field):
    _, ids = proposals
    with (
        pytest.raises(psycopg2.errors.NotNullViolation),
        get_connection() as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            sql.SQL("UPDATE improvement_proposals SET {}=NULL WHERE id=%s").format(
                sql.Identifier(field)
            ),
            (ids[0],),
        )


@pytest.mark.parametrize(
    "sort",
    ["target_kind", "title ASC", "action_asc;DROP TABLE improvement_proposals", ""],
)
def test_proposal_order_rejects_invalid_http_and_core_keys_before_sql(
    monkeypatch, sort
):
    app = FastAPI()
    app.include_router(router, prefix="/proposals")
    assert TestClient(app).get("/proposals", params={"sort": sort}).status_code == 422
    monkeypatch.setattr(
        base, "get_connection", lambda: pytest.fail("Invalid sort reached SQL")
    )
    with pytest.raises(ValueError, match="Sort must be one of"):
        list_proposals(sort=sort)
