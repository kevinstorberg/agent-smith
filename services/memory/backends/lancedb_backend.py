"""LanceDB backend for agent memory (local embedded vector store)."""

from __future__ import annotations

import os
from pathlib import Path

import lancedb
from langchain_community.vectorstores import LanceDB as LanceDBVectorStore

from scripts.shared.validation import validate_memory_id

STORE_PATH = Path(os.environ.get(
    "MEMORY_STORE_PATH",
    str(Path(__file__).parent.parent.parent.parent / "memory_store"),
))
TABLE_NAME = "memories"


def _db() -> lancedb.DBConnection:
    STORE_PATH.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(STORE_PATH))


def _get_table():
    """Return the memories table, or None if it doesn't exist or is empty."""
    db = _db()
    if TABLE_NAME not in db.table_names():
        return None
    return db.open_table(TABLE_NAME)


def init() -> None:
    STORE_PATH.mkdir(parents=True, exist_ok=True)
    _db()


def get_vectorstore(embeddings) -> VectorStore:
    return LanceDBVectorStore(
        connection=_db(),
        embedding=embeddings,
        table_name=TABLE_NAME,
        mode="append",
    )


def load_all() -> list[dict]:
    tbl = _get_table()
    if not tbl or tbl.count_rows() == 0:
        return []
    return tbl.search().limit(10000).to_list()


def list_rows(repo: str | None = None, limit: int = 20) -> list[dict]:
    tbl = _get_table()
    if not tbl or tbl.count_rows() == 0:
        return []
    rows = tbl.search().limit(limit * 5).to_list()
    if repo:
        rows = [r for r in rows if r.get("metadata", {}).get("repo") == repo]
    return rows[:limit]


def get_row(id: str) -> dict | None:
    validate_memory_id(id)
    tbl = _get_table()
    if not tbl:
        return None
    results = tbl.search().where(f"id = '{id}'", prefilter=True).limit(1).to_list()
    return results[0] if results else None


def delete_row(id: str) -> None:
    validate_memory_id(id)
    tbl = _get_table()
    if not tbl:
        raise KeyError(f"Memory not found: {id}")
    if not tbl.search().where(f"id = '{id}'", prefilter=True).limit(1).to_list():
        raise KeyError(f"Memory not found: {id}")
    tbl.delete(f"id = '{id}'")
