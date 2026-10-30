from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.routers.meeting_vocabulary import router
from services.db import get_connection
from services.meetings import vocabulary_db as db


@pytest.fixture
def vocabulary_rows():
    marker = uuid4().hex
    rows = [db.create(f"Term {index:02d} {marker}", f"Definition {marker}" + (" Important Topic" if index % 3 == 0 else ""))
            for index in reversed(range(25))]
    yield marker, list(reversed(rows))
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meeting_vocabulary WHERE id IN %s", (tuple(row["id"] for row in rows),))


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/meetings/vocabulary")
    return TestClient(app)


def test_vocabulary_list_filters_before_count_and_alphabetical_pagination(vocabulary_rows):
    marker, rows = vocabulary_rows
    first = db.list_terms(query=marker.upper(), limit=10)
    second = db.list_terms(query=marker, limit=10, offset=10)
    last = db.list_terms(query=marker, limit=10, offset=20)
    assert first["total"] == second["total"] == last["total"] == 25
    assert first["items"] + second["items"] + last["items"] == rows
    matches = db.list_terms(query="important TOPIC", limit=2, offset=2)
    assert matches["total"] == 9 and matches["items"] == rows[6:10:3]
    assert db.list_terms(query=marker, limit=10, offset=100) == {"items": [], "total": 25}
    assert db.list_terms(query="' OR true --") == {"items": [], "total": 0}


def test_vocabulary_default_shape_and_all_term_agent_matching_remain_compatible(vocabulary_rows):
    marker, rows = vocabulary_rows
    original = db.list_terms()
    assert set(original) == {"items", "total"}
    assert {row["id"] for row in rows} <= {row["id"] for row in original["items"]}
    assert set(original["items"][0]) == {"id", "term", "normalized_term", "definition", "revision", "created_at", "updated_at"}
    assert db.list_terms(query=marker, offset=22)["items"] == rows[22:]
    assert db.relevant(f"Discussed {rows[-1]['term'].upper()} today") == [{"term": rows[-1]["term"], "definition": rows[-1]["definition"]}]
    assert db.list_terms(query=marker, limit=10)["items"][-1]["id"] != rows[-1]["id"]


@pytest.mark.parametrize("values", [{"query": 5}, {"query": "x" * 1001}, {"limit": 0}, {"limit": 101},
                                  {"limit": True}, {"offset": -1}, {"offset": False}, {"offset": 1.5}])
def test_vocabulary_list_rejects_invalid_domain_queries(values):
    with pytest.raises(ValueError):
        db.list_terms(**values)


def test_vocabulary_http_list_and_exact_reader_preserve_records_outside_current_page(client, vocabulary_rows):
    marker, rows = vocabulary_rows
    first = client.get("/api/meetings/vocabulary", params={"q": marker, "limit": 10}).json()
    assert first["items"] == rows[:10] and first["total"] == 25
    detail = client.get(f"/api/meetings/vocabulary/{rows[-1]['id']}")
    assert detail.status_code == 200 and detail.json() == rows[-1]
    assert client.get("/api/meetings/vocabulary/not-a-uuid").status_code == 422
    assert client.get(f"/api/meetings/vocabulary/{uuid4()}").status_code == 404
    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"q": "x" * 1001}):
        assert client.get("/api/meetings/vocabulary", params=params).status_code == 422
    all_rows = client.get("/api/meetings/vocabulary").json()
    assert set(all_rows) == {"items", "total"} and {row["id"] for row in rows} <= {row["id"] for row in all_rows["items"]}
