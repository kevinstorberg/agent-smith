from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import services.memory.db as db
import services.memory.backends.lancedb_backend as lancedb_backend


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "lancedb")
    store = tmp_path / "store"
    with patch.object(lancedb_backend, "STORE_PATH", store):
        db._embeddings = None
        db._retriever = None
        yield
        db._retriever = None


def test_init_creates_store():
    db.init()
    assert lancedb_backend.STORE_PATH.exists()


def test_add_returns_uuid():
    id = db.add("test memory", repo="myrepo", tags=["test"])
    assert len(id) == 36


def test_list_memories_returns_added():
    db.add("first memory", repo="r")
    db.add("second memory", repo="r")
    memories = db.list_memories(repo="r")
    assert len(memories) == 2
    contents = {m["content"] for m in memories}
    assert "first memory" in contents
    assert "second memory" in contents


def test_list_memories_returns_full_list_no_internal_slice():
    count = db.DEFAULT_LIMIT + 5
    for i in range(count):
        db.add(f"memory {i}", repo="r")
    memories = db.list_memories()
    assert len(memories) == count


def test_list_filters_by_tags_and():
    db.add("both", tags=["a", "b"])
    db.add("only a", tags=["a"])
    db.add("b and c", tags=["b", "c"])
    matches = db.list_memories(tags=["a", "b"])
    assert len(matches) == 1
    assert matches[0]["content"] == "both"


def test_list_sorts_by_created_at_asc():
    ids = [db.add(f"m{i}") for i in range(5)]
    sorted_memories = db.list_memories(sort="created_at_asc")
    assert [m["id"] for m in sorted_memories] == ids


def test_list_sorts_by_updated_at_desc():
    first = db.add("first")
    second = db.add("second")
    db.update(first, content="first edited")
    sorted_memories = db.list_memories(sort="updated_at_desc")
    assert sorted_memories[0]["id"] == first
    assert sorted_memories[1]["id"] == second


def test_list_unknown_sort_raises():
    db.add("anything")
    with pytest.raises(ValueError, match="Unknown sort"):
        db.list_memories(sort="bogus")


def test_search_can_sort_by_created_at():
    ids = [db.add(f"keyword item {i}") for i in range(3)]
    results = db.search("keyword", sort="created_at_asc")
    returned = [r["id"] for r in results if r["id"] in ids]
    assert returned == ids


def test_search_default_sort_is_relevance():
    db.add("Python programming language")
    db.add("totally unrelated thing about cooking")
    results = db.search("Python coding")
    assert len(results) >= 1
    assert "Python" in results[0]["content"]


def test_search_with_date_sort_uses_retriever_not_load_all(monkeypatch):
    db.add("alpha entry")
    db.add("zebra entry")

    calls: list[str] = []
    original = lancedb_backend.load_all
    monkeypatch.setattr(
        lancedb_backend,
        "load_all",
        lambda: (calls.append("load_all"), original())[1],
    )

    db.search("anything", sort="created_at_desc")
    assert calls == [], "search() must filter via retriever, not bypass to load_all()"


def test_get_by_id():
    id = db.add("findable", repo="r")
    mem = db.get(id)
    assert mem is not None
    assert mem["content"] == "findable"
    assert mem["repo"] == "r"


def test_get_not_found():
    db.init()
    assert db.get("00000000-0000-0000-0000-000000000000") is None


def test_delete():
    id = db.add("to delete")
    db.delete(id)
    assert db.get(id) is None


def test_delete_not_found():
    db.init()
    with pytest.raises(KeyError):
        db.delete("00000000-0000-0000-0000-000000000000")


def test_update_content():
    id = db.add("old content", repo="r")
    db.update(id, content="new content")
    mem = db.get(id)
    assert mem["content"] == "new content"


def test_search_ranks_semantically():
    db.add("Python is a programming language used for web development")
    db.add("The weather in Paris is sunny today")
    results = db.search("coding in Python")
    assert len(results) >= 2
    assert "Python" in results[0]["content"]


def test_list_empty():
    db.init()
    assert db.list_memories() == []


def test_search_empty():
    db.init()
    assert db.search("anything") == []


def test_search_resilient_to_float_buffer_idx(monkeypatch):
    from langchain_core.documents import Document

    id = db.add("the quick brown fox", repo="r")
    retriever = db._get_retriever()

    fake_hit = Document(
        page_content="the quick brown fox",
        metadata={"id": id, "buffer_idx": 0.0},
    )
    monkeypatch.setattr(
        retriever.vectorstore,
        "similarity_search_with_relevance_scores",
        lambda *args, **kwargs: [(fake_hit, 0.9)],
    )

    results = db.search("fox")
    assert len(results) == 1
    assert results[0]["id"] == id
    assert results[0]["content"] == "the quick brown fox"


def test_time_weighting_prefers_recent():
    from datetime import datetime, timedelta
    from langchain_core.documents import Document

    retriever = db._get_retriever()

    old_time = datetime.now() - timedelta(days=30)
    old_doc = Document(
        page_content="database optimization techniques",
        metadata={
            "id": "00000000-0000-0000-0000-000000000001",
            "repo": "",
            "tags": "[]",
            "created_at": old_time.isoformat(),
            "updated_at": old_time.isoformat(),
            "last_accessed_at": old_time,
        },
    )
    retriever.add_documents([old_doc], ids=["00000000-0000-0000-0000-000000000001"], current_time=old_time)

    new_time = datetime.now()
    new_doc = Document(
        page_content="database optimization techniques",
        metadata={
            "id": "00000000-0000-0000-0000-000000000002",
            "repo": "",
            "tags": "[]",
            "created_at": new_time.isoformat(),
            "updated_at": new_time.isoformat(),
            "last_accessed_at": new_time,
        },
    )
    retriever.add_documents([new_doc], ids=["00000000-0000-0000-0000-000000000002"], current_time=new_time)

    results = db.search("database optimization")
    assert len(results) >= 2
    ids = [r["id"] for r in results]
    assert ids[0] == "00000000-0000-0000-0000-000000000002"
