import json
from uuid import uuid4

import pytest
from langchain_core.documents import Document

from services.api.routers import memory as memory_router
from services.db import get_connection
from services.memory import db
from services.memory.backends import get_backend, pgvector_backend
from tests.test_memory_publication import CREATED, isolated_store as isolated_store, metadata
from tests.test_profiles_router import client as client


@pytest.fixture(autouse=True, params=["lancedb", "pgvector"])
def memory_backend(request, isolated_store, monkeypatch):
    if request.param == "lancedb":
        yield
        return
    monkeypatch.setenv("MEMORY_BACKEND", "pgvector")
    pgvector_backend._initialized = False
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM memories")
    yield
    pgvector_backend._initialized = False
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM memories")


def seed_legacy(memory_id, content, meeting_id, repo="work"):
    get_backend().get_vectorstore(db._get_embeddings()).add_documents([
        Document(page_content=content, metadata=metadata(memory_id, repo=repo, tags=json.dumps(["meeting-memory", f"meeting:{meeting_id}", "preference"]))),
    ], ids=[memory_id])


def test_meeting_provenance_filters_before_pagination_and_survives_human_edits(client):
    meeting_id, shared_id, legacy_id = str(uuid4()), str(uuid4()), str(uuid4())
    seed_legacy(legacy_id, "An older meeting preference", meeting_id)
    db.add("A general memory", repo="work", tags=["decision"])
    db.publish(shared_id, "A reusable meeting decision", repo="work", tags=["decision"],
               created_at=CREATED, source_type="meeting", source_id=meeting_id)
    ordinary = db.add("Another general memory", repo="work", tags=["preference"])
    rows = memory_router.list_all(repo="work", tags=[], sort="created_at_asc", limit=1, offset=0, meeting_only=True)
    assert rows["total"] == 2 and len(rows["items"]) == 1
    assert rows["items"][0]["from_meeting"] is True
    assert {item["id"] for item in db.list_memories(meeting_only=True)} == {shared_id, legacy_id}
    assert len(db.list_memories()) == 4
    assert db.get(ordinary)["from_meeting"] is False
    assert db.get(legacy_id)["source_id"] == meeting_id
    db.update(shared_id, content="Human refinement", tags=["edited"])
    db.update(legacy_id, tags=["edited"])
    db._retriever = None
    for item_id in (shared_id, legacy_id):
        item = db.get(item_id)
        assert item["source_type"] == "meeting" and item["source_id"] == meeting_id and item["from_meeting"]
    assert {item["id"] for item in db.search("meeting", meeting_only=True)} == {shared_id, legacy_id}
    response = client.get("/api/memory/list", params={"meeting_only": "true", "tags": "edited"})
    assert response.status_code == 200 and response.json()["total"] == 2
    assert client.get("/api/memory/list", params={"meeting_only": "unrecognized"}).status_code == 422


def test_legacy_meeting_origin_is_read_without_mutating_the_backend():
    meeting_id, memory_id = str(uuid4()), str(uuid4())
    seed_legacy(memory_id, "Legacy meeting", meeting_id, repo="")
    assert get_backend().get_row(memory_id)["metadata"].get("source_type") is None
    first = db.get(memory_id)
    assert first["from_meeting"] and first["source_id"] == meeting_id
    assert db.publish(memory_id, "Legacy meeting", tags=first["tags"], created_at=CREATED,
                      source_type="meeting", source_id=meeting_id) == memory_id
    assert get_backend().get_row(memory_id)["metadata"].get("source_type") is None
    assert db._to_row(content="Unknown", id=str(uuid4()), meta={"tags": ["meeting-memory"]})["from_meeting"] is False


def test_ordinary_tag_edits_cannot_reclassify_a_general_memory_as_a_meeting():
    meeting_id = str(uuid4())
    memory_id = db.add("A general memory", tags=["ordinary"])
    db.update(memory_id, tags=["meeting-memory", f"meeting:{meeting_id}"])
    db._retriever = None
    item = db.get(memory_id)
    assert item["source_type"] == "general" and item["source_id"] == memory_id
    assert item["from_meeting"] is False
    assert db.list_memories(meeting_only=True) == []
