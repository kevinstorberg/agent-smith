from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from services.api.models import base
from services.api.models.audit import list_events
from services.api.routers.audit import router
from services.db import get_connection


@pytest.fixture
def rows():
    marker = "audit-sort-" + uuid4().hex
    specs = [
        ("Zulu", "success", "codex", 30, "Beta", 1),
        ("alpha", "pending", "claude", None, "Alpha", 3),
        ("ALPHA", "error", "gemini", 10, None, 2),
        ("charlie", "pending", "claude", 10, "", 2),
        ("bravo", "success", "codex", 0, "ALPHA", 1),
        ("delta", "error", "gemini", None, "Beta", 4),
    ]
    ids = []
    with get_connection() as conn, conn.cursor() as cur:
        for tool, status, agent, duration, project, day in specs:
            cur.execute(
                'INSERT INTO tool_call_events(correlation_key,session_id,tool_name,status,agent,duration_ms,project,created_at,tool_input) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,\'{"full":"source"}\'::jsonb) RETURNING id',
                (
                    marker + tool,
                    marker,
                    tool,
                    status,
                    agent,
                    duration,
                    project,
                    datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=day),
                ),
            )
            ids.append(cur.fetchone()[0])
    yield marker, ids
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM tool_call_events WHERE session_id=%s", (marker,))


_ORDERS = [
    ("tool_asc", [1, 2, 4, 3, 5, 0]),
    ("tool_desc", [0, 5, 3, 4, 2, 1]),
    ("status_asc", [2, 5, 1, 3, 0, 4]),
    ("status_desc", [4, 0, 3, 1, 5, 2]),
    ("agent_asc", [1, 3, 0, 4, 2, 5]),
    ("agent_desc", [5, 2, 4, 0, 3, 1]),
    ("duration_asc", [4, 2, 3, 0, 1, 5]),
    ("duration", [0, 3, 2, 4, 5, 1]),
    ("project_asc", [1, 4, 0, 5, 2, 3]),
    ("project_desc", [5, 0, 4, 1, 3, 2]),
    ("oldest", [0, 4, 2, 3, 1, 5]),
    ("newest", [5, 1, 3, 2, 4, 0]),
]


@pytest.mark.parametrize("sort,positions", _ORDERS)
def test_audit_orders_complete_filtered_results_before_pagination(
    rows, sort, positions
):
    marker, ids = rows
    app = FastAPI()
    app.include_router(router, prefix="/audit")
    client = TestClient(app)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM tool_call_events WHERE session_id=%s ORDER BY id", (marker,)
        )
        before = cur.fetchall()
    pages = [
        client.get(
            "/audit/events",
            params={"q": marker, "sort": sort, "limit": 2, "offset": offset},
        )
        for offset in (0, 2, 4)
    ]
    assert all(page.status_code == 200 for page in pages), [page.text for page in pages]
    assert [row["id"] for page in pages for row in page.json()["items"]] == [
        ids[index] for index in positions
    ]
    assert [page.json()["total"] for page in pages] == [6, 6, 6]
    assert all(
        "tool_input" not in row and "result" not in row
        for page in pages
        for row in page.json()["items"]
    )
    assert list_events(q=marker, sort=sort, limit=2, offset=99) == ([], 6)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM tool_call_events WHERE session_id=%s ORDER BY id", (marker,)
        )
        assert cur.fetchall() == before


def test_audit_sort_preserves_exact_filters_and_counts(rows):
    marker, ids = rows
    page, total = list_events(
        q=marker, status="pending", agent="claude", sort="tool_desc", limit=1, offset=1
    )
    assert total == 2 and [row["id"] for row in page] == [ids[1]]
    page, total = list_events(q=marker, project="Beta", sort="duration_asc", limit=1)
    assert total == 2 and [row["id"] for row in page] == [ids[0]]


@pytest.mark.parametrize(
    "sort", ["tool_name", "tool_asc;DROP TABLE tool_call_events", "duration DESC", ""]
)
def test_audit_invalid_order_is_rejected_at_http_and_before_sql(monkeypatch, sort):
    app = FastAPI()
    app.include_router(router, prefix="/audit")
    assert (
        TestClient(app).get("/audit/events", params={"sort": sort}).status_code == 422
    )

    def unexpected_connection():
        pytest.fail("Unknown sort reached SQL")

    monkeypatch.setattr(base, "get_connection", unexpected_connection)
    with pytest.raises(ValueError):
        list_events(sort=sort)
