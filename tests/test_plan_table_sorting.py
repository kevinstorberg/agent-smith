from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from services.api.models.plan import create_plan, list_plans
from services.db import get_connection


@pytest.fixture
def ordered_plans():
    marker = "table-sort-" + uuid4().hex
    specs = [
        ("zulu", "final", "Beta", 1),
        ("alpha", "draft", "Alpha", 3),
        ("ALPHA", "final", None, 2),
        ("charlie", "draft", None, 2),
        ("bravo", "final", "ALPHA", 1),
        ("delta", "draft", "Beta", 4),
    ]
    ids = []
    stamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    try:
        for title, status, project, day in specs:
            item_id = create_plan(
                f"{marker} {title}", f"Full document for {title}" * 100, project, status
            )
            ids.append(item_id)
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE plans SET created_at=%s, updated_at=%s WHERE id=%s",
                    (stamp + timedelta(days=day), stamp + timedelta(days=day), item_id),
                )
        outsider = create_plan(
            "unrelated aardvark " + uuid4().hex, "Unrelated document", "Beta", "draft"
        )
        ids.append(outsider)
        yield marker, ids[:6]
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM plans WHERE id=ANY(%s)", (ids,))


_ORDERS = [
    ("title", [1, 2, 4, 3, 5, 0]),
    ("title_desc", [0, 5, 3, 4, 2, 1]),
    ("status_asc", [1, 3, 5, 0, 2, 4]),
    ("status_desc", [4, 2, 0, 5, 3, 1]),
    ("project_asc", [1, 4, 0, 5, 2, 3]),
    ("project_desc", [5, 0, 4, 1, 3, 2]),
    ("updated_asc", [0, 4, 2, 3, 1, 5]),
    ("updated", [5, 1, 3, 2, 4, 0]),
]


@pytest.mark.parametrize("sort,positions", _ORDERS)
def test_plan_table_order_is_global_stable_and_null_last_before_pagination(
    ordered_plans, sort, positions
):
    marker, ids = ordered_plans
    pages = [
        list_plans(q=marker, sort=sort, limit=2, offset=offset) for offset in (0, 2, 4)
    ]
    assert [row["id"] for page, _ in pages for row in page] == [
        ids[index] for index in positions
    ]
    assert [total for _, total in pages] == [6, 6, 6]
    assert all(
        set(row) == {"id", "title", "project", "status", "created_at", "updated_at"}
        for page, _ in pages
        for row in page
    )
    assert list_plans(q=marker, sort=sort, limit=2, offset=99) == ([], 6)


@pytest.mark.parametrize("sort,positions", _ORDERS)
def test_plan_table_http_accepts_every_header_direction(ordered_plans, sort, positions):
    from services.api.app import app

    marker, ids = ordered_plans
    response = TestClient(app).get(
        "/api/plans", params={"q": marker, "sort": sort, "limit": 2, "offset": 2}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 6
    assert [row["id"] for row in response.json()["items"]] == [
        ids[index] for index in positions[2:4]
    ]


def test_plan_sort_preserves_filters_counts_and_document_content(ordered_plans):
    marker, ids = ordered_plans
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM plans WHERE id=ANY(%s) ORDER BY id", (ids,))
        before = cur.fetchall()
    draft_page, total = list_plans(
        q=marker, status="draft", sort="title_desc", limit=2, offset=1
    )
    assert total == 3
    assert [row["id"] for row in draft_page] == [ids[3], ids[1]]
    project_page, total = list_plans(
        q=marker, project="Beta", sort="updated_asc", limit=1, offset=1
    )
    assert total == 2 and [row["id"] for row in project_page] == [ids[5]]
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM plans WHERE id=ANY(%s) ORDER BY id", (ids,))
        assert cur.fetchall() == before


@pytest.mark.parametrize(
    "sort,positions",
    [
        ("title", [1, 2, 4, 3, 5, 0]),
        ("updated", [5, 1, 3, 2, 4, 0]),
        ("newest", [5, 1, 3, 2, 4, 0]),
    ],
)
def test_plan_legacy_sort_aliases_keep_their_order(ordered_plans, sort, positions):
    marker, ids = ordered_plans
    rows, total = list_plans(q=marker, sort=sort)
    assert total == 6
    assert [row["id"] for row in rows] == [ids[index] for index in positions]


def test_plan_non_ascii_title_order_uses_postgres_lower_and_stable_id_ties():
    marker = "unicode-sort-" + uuid4().hex
    ids = [
        create_plan(f"{marker} {title}", "Full unicode document")
        for title in ("éCLAIR", "Éclair", "ÉCLAIR")
    ]
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT lower('éCLAIR'), lower('Éclair'), lower('ÉCLAIR')")
            lower, upper, upper_ascii = cur.fetchone()
        assert upper == upper_ascii
        # PostgreSQL lower() follows its database locale, independently of JavaScript.
        ascending = ids if lower == upper else [ids[1], ids[2], ids[0]]
        rows, total = list_plans(q=marker, sort="title", limit=1)
        assert total == 3 and rows[0]["id"] == ascending[0]
        pages = [
            list_plans(q=marker, sort="title_desc", limit=1, offset=index)[0]
            for index in range(3)
        ]
        assert [row["id"] for page in pages for row in page] == list(
            reversed(ascending)
        )
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM plans WHERE id=ANY(%s)", (ids,))


@pytest.mark.parametrize(
    "sort,positions",
    [("project_asc", [3, 2, 0, 1]), ("project_desc", [2, 3, 1, 0])],
)
def test_plan_project_sort_places_empty_and_null_display_values_last(sort, positions):
    from services.api.models.plan import get_plan

    marker = "missing-project-" + uuid4().hex
    ids = [
        create_plan(f"{marker} {index}", "Full document", project=project)
        for index, project in enumerate(("", None, "Beta", "Alpha"))
    ]
    try:
        assert get_plan(ids[0])["project"] == ""
        rows, total = list_plans(q=marker, sort=sort, limit=2)
        rest, rest_total = list_plans(q=marker, sort=sort, limit=2, offset=2)
        assert total == rest_total == 4
        assert [row["id"] for row in rows + rest] == [ids[index] for index in positions]
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM plans WHERE id=ANY(%s)", (ids,))


@pytest.mark.parametrize(
    "sort", ["title;DROP TABLE plans", "title DESC", "project", "updated_desc", ""]
)
def test_plan_sort_rejects_untrusted_keys_at_http_and_core_boundaries(
    monkeypatch, sort
):
    from services.api.app import app
    from services.api.models import base

    assert TestClient(app).get("/api/plans", params={"sort": sort}).status_code == 422

    def unexpected_database_connection():
        pytest.fail("Invalid sort reached the database boundary")

    monkeypatch.setattr(base, "get_connection", unexpected_database_connection)
    with pytest.raises(ValueError, match="Sort must be one of"):
        list_plans(sort=sort)
