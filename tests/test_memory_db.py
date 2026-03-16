"""Integration tests for services/memory/db.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import services.memory.db as db


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path):
    """Point the memory store at a temp directory for every test."""
    with patch.object(db, "STORE_PATH", tmp_path / "store"):
        db._model = None  # allow lazy load to cache across tests in this module
        yield


def test_init_creates_store():
    db.init()
    assert db.STORE_PATH.exists()


def test_add_returns_uuid():
    id = db.add("test memory", repo="myrepo", tags=["test"])
    assert len(id) == 36  # UUID format


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
