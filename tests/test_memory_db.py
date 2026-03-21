from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import services.memory.db as db
import services.memory.backends.lancedb_backend as lancedb_backend


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path):
    """Point the memory store at a temp directory and reset caches for every test."""
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


def test_time_weighting_prefers_recent():
    """Recent memories should rank higher than old ones when content is identical."""
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
