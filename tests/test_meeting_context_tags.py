import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.documents import Document

from services.api.routers import memory as memory_router
from services.meetings import db as meeting_db, labels_db
from services.meetings.analysis import _safe_rows
from services.memory import db, server
from services.memory.backends import get_backend
from tests.test_memory_publication import CREATED, isolated_store as isolated_store, metadata
from tests.test_meetings_router import saved as saved


def seed_legacy(memory_id, meeting_id):
    get_backend().get_vectorstore(db._get_embeddings()).add_documents([
        Document(page_content="An earlier security decision", metadata=metadata(memory_id, repo="context-test", tags=json.dumps(["meeting-memory", f"meeting:{meeting_id}", "decision"]))),
    ], ids=[memory_id])


def test_public_reads_inherit_whole_meeting_subjects_before_tag_filter_and_limit(saved, monkeypatch):
    meeting_id = saved[1][0]["id"]
    labels_db.update(meeting_id, 0, ["security", "paralign", "roadmap"])
    legacy, current = str(uuid4()), str(uuid4())
    seed_legacy(legacy, meeting_id)
    db.publish(current, "A security commitment", repo="context-test", tags=["commitment"], created_at=CREATED, source_type="meeting", source_id=meeting_id)
    general = db.add("General security context", repo="context-test", tags=["security"])
    lookups = []
    original = labels_db.for_memories

    def counted(ids):
        lookups.append(ids)
        return original(ids)

    monkeypatch.setattr(labels_db, "for_memories", counted)
    rows = db.list_memories(repo="context-test", tags=["security", "paralign"], limit=1)
    assert len(rows) == 1 and rows[0]["id"] in {legacy, current}
    assert lookups == [[meeting_id]]
    assert rows[0]["tags"] in (["decision"], ["commitment"])
    assert rows[0]["context_tags"] == ["security", "paralign", "roadmapping"]
    assert db.get(general)["context_tags"] == []
    assert _safe_rows(rows)[0]["context_tags"] == rows[0]["context_tags"]
    for read in (db.search_fresh, db.search, server.memory_search):
        assert {row["id"] for row in read("security", repo="context-test", tags=["security", "paralign"], limit=10)} == {legacy, current}
        assert read("security", repo="context-test", tags=["security", "hiring"], limit=10) == []
    listed = memory_router.list_all(repo="context-test", tags=["security", "paralign"], sort="created_at_asc", limit=1, offset=1, meeting_only=True)
    assert listed["total"] == 2 and len(listed["items"]) == 1
    assert server.memory_list(repo="context-test", tags=["security", "decision"], meeting_only=True)[0]["id"] == legacy


def test_live_label_edits_do_not_change_raw_memory_or_frozen_replay(saved, monkeypatch):
    meeting_id, memory_id = saved[1][0]["id"], str(uuid4())
    seed_legacy(memory_id, meeting_id)
    original = deepcopy(get_backend().get_row(memory_id))
    raw_tags = json.loads(original["metadata"]["tags"])

    def forbidden(*args, **kwargs):
        raise AssertionError("Updating meeting context must not rewrite or embed a saved memory")

    monkeypatch.setattr(db, "_persist_document", forbidden)
    labels_db.update(meeting_id, 0, ["product", "roadmapping"])
    assert db.get(memory_id)["context_tags"] == ["product", "roadmapping"]
    assert get_backend().get_row(memory_id) == original
    assert db.publish(memory_id, original["text"], repo="context-test", tags=raw_tags, created_at=CREATED, source_type="meeting", source_id=meeting_id) == memory_id
    labels_db.update(meeting_id, 1, [])
    assert db.get(memory_id)["context_tags"] == []
    assert get_backend().get_row(memory_id) == original


def test_human_own_tag_edit_preserves_context_tags_and_source(saved):
    meeting_id, memory_id = saved[1][0]["id"], str(uuid4())
    labels_db.update(meeting_id, 0, ["security"])
    db.publish(memory_id, "A security decision", repo="context-test", tags=["vendor-evaluation"], created_at=CREATED, source_type="meeting", source_id=meeting_id)
    db.update(memory_id, tags=["human-topic"])
    row = db.get(memory_id)
    assert row["tags"] == ["human-topic"] and row["context_tags"] == ["security"]
    assert row["source_id"] == meeting_id and row["from_meeting"]
    assert db.list_memories(tags=["human-topic", "security"])[0]["id"] == memory_id


def test_unavailable_or_missing_sources_do_not_expose_meeting_labels(saved):
    meeting_id, memory_id = saved[1][0]["id"], str(uuid4())
    labels_db.update(meeting_id, 0, ["security"])
    db.publish(memory_id, "A security decision", tags=["fact"], created_at=CREATED, source_type="meeting", source_id=meeting_id)
    assert db.get(memory_id)["context_tags"] == ["security"]
    with meeting_db._cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET available = false WHERE id = %s", (meeting_id,))
    assert db.get(memory_id)["context_tags"] == []
    assert db.list_memories(tags=["security"]) == []


def test_context_lookup_failure_is_descriptive_but_raw_publication_is_independent(saved, monkeypatch):
    meeting_id, memory_id = saved[1][0]["id"], str(uuid4())
    db.publish(memory_id, "A security decision", tags=["fact"], created_at=CREATED, source_type="meeting", source_id=meeting_id)

    def failed(*args, **kwargs):
        raise meeting_db.MeetingStorageError("SECRET_DIAGNOSTIC")

    monkeypatch.setattr(labels_db, "for_memories", failed)
    with pytest.raises(db.MemoryContextUnavailable, match="Meeting context labels could not be read") as caught:
        db.get(memory_id)
    assert "SECRET" not in str(caught.value)
    assert db.publish(memory_id, "A security decision", tags=["fact"], created_at=CREATED, source_type="meeting", source_id=meeting_id) == memory_id
    assert db.add("Ordinary general memory")


def test_context_source_validation_does_not_guess_origin_from_general_memory(saved):
    meeting_id = saved[1][0]["id"]
    labels_db.update(meeting_id, 0, ["security"])
    rows = [
        {"id": "general", "source_id": meeting_id, "from_meeting": False},
        {"id": "upper", "source_id": meeting_id.upper(), "from_meeting": True},
        {"id": "invalid", "source_id": "not-a-uuid", "from_meeting": True},
    ]
    assert [row["context_tags"] for row in db._with_context_tags(rows)] == [[], ["security"], []]


def test_semantic_context_filter_preserves_bounded_candidates_and_list_uses_cached_stream(saved, monkeypatch):
    meeting_id, matching_id = saved[1][0]["id"], str(uuid4())
    labels_db.update(meeting_id, 0, ["security"])
    docs = [db._memory_document(str(uuid4()), "Higher ranked general candidate", None, [], CREATED, CREATED)
            for _ in range(db.SEARCH_FETCH_CEILING)]
    docs.append(db._memory_document(matching_id, "Lower ranked meeting candidate", None, [], CREATED, CREATED,
                                    source_type="meeting", source_id=meeting_id))
    fresh_limits, ordinary_limits = [], []

    def similarity_search(query, *, k):
        fresh_limits.append(k)
        return docs[:k]

    retriever = SimpleNamespace(memory_stream=docs, k=10)

    def invoke(query):
        ordinary_limits.append(retriever.k)
        return docs[:retriever.k]

    retriever.invoke = invoke
    monkeypatch.setattr(db, "get_backend", lambda: SimpleNamespace(get_vectorstore=lambda embeddings: SimpleNamespace(similarity_search=similarity_search)))
    monkeypatch.setattr(db, "_get_retriever", lambda: retriever)
    assert db.search_fresh("candidate", tags=["security"], limit=1) == []
    assert db.search("candidate", tags=["security"], limit=1) == []
    assert fresh_limits == [20] and ordinary_limits == [db.SEARCH_FETCH_CEILING]
    assert [row["id"] for row in db.list_memories(tags=["security"], limit=1)] == [matching_id]
