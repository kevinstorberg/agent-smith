from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import services.memory.db as db
import services.memory.backends.lancedb_backend as lb


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "lancedb")
    store = tmp_path / "store"
    with patch.object(lb, "STORE_PATH", store):
        db._embeddings = None
        db._retriever = None
        yield
        db._retriever = None


def test_init_creates_directory():
    lb.init()
    assert lb.STORE_PATH.exists()


def test_get_table_returns_none_before_data():
    lb.init()
    assert lb._get_table() is None


def test_load_all_empty():
    lb.init()
    assert lb.load_all() == []


def test_list_rows_empty():
    assert lb.list_rows() == []


def test_get_row_not_found():
    lb.init()
    assert lb.get_row("12345678-1234-1234-1234-123456789abc") is None


def test_delete_row_not_found():
    lb.init()
    with pytest.raises(KeyError, match="Memory not found"):
        lb.delete_row("12345678-1234-1234-1234-123456789abc")


def test_get_row_after_add():
    mem_id = db.add("test content", repo="test-repo", tags=["tag1"])
    row = lb.get_row(mem_id)
    assert row is not None
    assert row["id"] == mem_id


def test_list_rows_returns_data():
    db.add("memory one", repo="r1", tags=[])
    db.add("memory two", repo="r2", tags=[])
    rows = lb.list_rows()
    assert len(rows) >= 2


def test_list_rows_filters_by_repo():
    db.add("in repo", repo="target", tags=[])
    db.add("other repo", repo="other", tags=[])
    rows = lb.list_rows(repo="target")
    assert all(r.get("metadata", {}).get("repo") == "target" for r in rows)


def test_load_all_returns_data():
    db.add("loaded memory", repo="", tags=[])
    rows = lb.load_all()
    assert len(rows) >= 1


def test_delete_row_removes_entry():
    mem_id = db.add("to delete", repo="", tags=[])
    assert lb.get_row(mem_id) is not None
    lb.delete_row(mem_id)
    assert lb.get_row(mem_id) is None


def test_get_row_rejects_invalid_id():
    with pytest.raises(ValueError, match="Invalid memory ID"):
        lb.get_row("not-a-uuid")


def test_delete_row_rejects_invalid_id():
    with pytest.raises(ValueError, match="Invalid memory ID"):
        lb.delete_row("not-a-uuid")
