from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from langchain_core.documents import Document

from services.memory import db
from services.memory.backends import lancedb_backend
from tests.test_pgvector_backend import FakeEmbeddings

CREATED = "2026-01-27T15:30:00+00:00"


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "lancedb")
    monkeypatch.setattr(lancedb_backend, "STORE_PATH", tmp_path / "memories")
    monkeypatch.setattr(db, "_embeddings", FakeEmbeddings())
    monkeypatch.setattr(db, "_retriever", None)
    yield
    db._retriever = None
    db._embeddings = None


def no_full_load(*args, **kwargs):
    raise AssertionError("Frozen publication and fresh search must not load the entire store")


def metadata(id, *, repo="meeting-project", tags=None):
    return {
        "id": id, "repo": repo, "tags": tags if tags is not None else '["meeting-memory"]',
        "created_at": CREATED, "updated_at": CREATED, "last_accessed_at": datetime(2026, 1, 27, 15, 30), "buffer_idx": 0,
    }


def test_cold_publish_and_fresh_search_never_initialize_or_load_retriever(monkeypatch):
    id = str(uuid4())
    monkeypatch.setattr(lancedb_backend, "load_all", no_full_load)
    monkeypatch.setattr(db, "_get_retriever", no_full_load)
    assert db.publish(id.upper(), "Python architecture decision", repo="meeting-project", tags=["meeting-memory"], created_at=CREATED) == id
    saved = db.get(id)
    assert saved["content"] == "Python architecture decision" and saved["created_at"] == CREATED
    assert db._retriever is None
    assert db.search_fresh("Python", repo="meeting-project", tags=["meeting-memory"])[0]["id"] == id
    assert db._retriever is None
    with monkeypatch.context() as patch:
        patch.setattr(lancedb_backend, "get_vectorstore", no_full_load)
        assert db.publish(id, saved["content"], repo="meeting-project", tags=["meeting-memory"], created_at="2026-01-27T10:30:00-05:00") == id
    assert db.get(id) == saved


def test_cold_publish_preserves_legacy_add_update_and_lancedb_metadata_schema():
    id = str(uuid4())
    db.publish(id, "Imported fact", created_at=CREATED)
    later = db.add("Ordinary memory", repo="legacy", tags=["original"])
    db.update(id, content="Human correction")
    db.update(later, tags=["edited"])
    assert db.get(id)["content"] == "Human correction" and db.get(id)["created_at"] == CREATED
    rows = {item["id"]: item for item in db.list_memories()}
    assert set(rows) == {id, later}
    assert rows[later]["tags"] == ["edited"]


def test_publish_updates_warm_cache_only_after_successful_write(monkeypatch):
    db.add("Existing memory")
    retriever = db._get_retriever()
    id = str(uuid4())
    original = retriever.vectorstore.add_documents

    def write(documents, **kwargs):
        assert all(item.metadata.get("id") != id for item in retriever.memory_stream)
        return original(documents, **kwargs)

    monkeypatch.setattr(retriever.vectorstore, "add_documents", write)
    monkeypatch.setattr(lancedb_backend, "load_all", no_full_load)
    db.publish(id, "New frozen memory", created_at=CREATED)
    matches = [item for item in retriever.memory_stream if item.metadata.get("id") == id]
    assert len(matches) == 1 and matches[0].page_content == "New frozen memory"
    assert isinstance(matches[0].metadata["last_accessed_at"], datetime)
    db.publish(id, "New frozen memory", created_at=CREATED)
    assert len([item for item in retriever.memory_stream if item.metadata.get("id") == id]) == 1


def test_publication_replay_after_delayed_fetch_does_not_duplicate_cache(monkeypatch):
    id = str(uuid4())
    db.publish(id, "Frozen memory", created_at=CREATED)
    retriever = db._get_retriever()
    with monkeypatch.context() as patch:
        patch.setattr(db, "get", lambda key: None)
        db.publish(id, "Frozen memory", created_at=CREATED)
    assert len([item for item in retriever.memory_stream if item.metadata.get("id") == id]) == 1
    assert lancedb_backend._get_table().count_rows() == 1


@pytest.mark.parametrize("change", [
    {"content": "Private changed content"}, {"repo": "another-project"}, {"tags": ["human-edit"]},
    {"created_at": "2026-01-28T15:30:00+00:00"},
])
def test_frozen_publication_conflicts_leave_existing_memory_unchanged(change):
    kwargs = {"id": str(uuid4()), "content": "Original private memory", "repo": "meeting-project", "tags": ["meeting-memory"], "created_at": CREATED}
    db.publish(**kwargs)
    original = db.get(kwargs["id"])
    with pytest.raises(db.MemoryConflictError) as caught:
        db.publish(**{**kwargs, **change})
    assert "private" not in str(caught.value).lower()
    assert db.get(kwargs["id"]) == original


def test_frozen_replay_does_not_overwrite_a_human_correction():
    id = str(uuid4())
    db.publish(id, "Original generated memory", created_at=CREATED)
    db.update(id, content="Corrected by a person")
    with pytest.raises(db.MemoryConflictError):
        db.publish(id, "Original generated memory", created_at=CREATED)
    assert db.get(id)["content"] == "Corrected by a person"


def test_failed_publication_does_not_mutate_warm_cache(monkeypatch):
    db.add("Keep this memory")
    retriever = db._get_retriever()
    before = deepcopy(retriever.memory_stream)
    id = str(uuid4())

    def failed_write(*args, **kwargs):
        raise RuntimeError("Synthetic write failure")

    monkeypatch.setattr(retriever.vectorstore, "add_documents", failed_write)
    with pytest.raises(RuntimeError, match="Synthetic write failure"):
        db.publish(id, "Uncommitted memory", created_at=CREATED)
    assert retriever.memory_stream == before
    assert db.get(id) is None


def test_fresh_search_sees_external_write_missing_from_warm_cached_stream(monkeypatch):
    existing = db.add("Python architecture")
    retriever = db._get_retriever()
    external = str(uuid4())
    store = lancedb_backend.get_vectorstore(db._get_embeddings())
    store.add_documents([Document(page_content="Weather from another process", metadata=metadata(external))], ids=[external])
    monkeypatch.setattr(lancedb_backend, "load_all", no_full_load)
    assert [item["id"] for item in db.search_fresh("weather", limit=1)] == [external]
    assert [item.metadata["id"] for item in retriever.memory_stream] == [existing]


def test_fresh_search_of_cold_empty_lancedb_is_empty_without_loading(monkeypatch):
    monkeypatch.setattr(lancedb_backend, "load_all", no_full_load)
    assert db.search_fresh("Anything") == []
    assert db._retriever is None


@pytest.mark.parametrize("shape", ["pgvector", "pinecone"])
@pytest.mark.parametrize("limit,candidates", [(1, 20), (10, 50), (100, 200)])
def test_fresh_search_serializes_backend_shapes_and_bounds_candidates(monkeypatch, shape, limit, candidates):
    match = str(uuid4())
    hit_metadata = metadata(match)
    if shape == "pinecone":
        hit_metadata.pop("id")
        hit_metadata["tags"] = ["meeting-memory"]
    docs = [
        Document(page_content="Excluded project", metadata=metadata(str(uuid4()), repo="other")),
        Document(id=match if shape == "pinecone" else None, page_content="Matching memory", metadata=hit_metadata),
    ]
    store = SimpleNamespace(similarity_search=Mock(return_value=docs))
    backend = SimpleNamespace(get_vectorstore=Mock(return_value=store), load_all=no_full_load)
    monkeypatch.setattr(db, "get_backend", lambda: backend)
    monkeypatch.setattr(db, "_get_retriever", no_full_load)
    assert db.search_fresh("topic", repo="meeting-project", tags=["meeting-memory"], limit=limit) == [{
        "id": match, "content": "Matching memory", "repo": "meeting-project", "tags": ["meeting-memory"],
        "created_at": CREATED, "updated_at": CREATED,
    }]
    store.similarity_search.assert_called_once_with("topic", k=candidates)


@pytest.mark.parametrize("change", [
    {"id": "private invalid id"}, {"id": None}, {"content": " "}, {"content": None},
    {"created_at": "2026-01-27T15:30:00"}, {"created_at": "private invalid date"}, {"created_at": None},
    {"repo": []}, {"repo": " "}, {"tags": "private tags"}, {"tags": [" "]}, {"tags": [1]},
])
def test_publish_validates_inputs_before_backend_access(monkeypatch, change):
    monkeypatch.setattr(db, "get_backend", no_full_load)
    kwargs = {"id": str(uuid4()), "content": "Frozen memory", "created_at": CREATED, **change}
    with pytest.raises(ValueError) as caught:
        db.publish(**kwargs)
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("change", [
    {"query": " "}, {"query": None}, {"query": "x" * 1001},
    {"limit": 0}, {"limit": 101}, {"limit": True}, {"limit": 1.5},
    {"repo": []}, {"tags": [None]},
])
def test_fresh_search_validates_inputs_before_backend_access(monkeypatch, change):
    monkeypatch.setattr(db, "get_backend", no_full_load)
    with pytest.raises(ValueError):
        db.search_fresh(**{"query": "topic", **change})
