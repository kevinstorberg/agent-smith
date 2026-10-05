from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import lancedb
from langchain_core.vectorstores import VectorStore
from langchain_community.vectorstores import LanceDB as LanceDBVectorStore
from langchain_core.documents import Document

from scripts.shared.validation import validate_memory_id
from services.config import MEMORY_STORE_PATH

STORE_PATH = Path(MEMORY_STORE_PATH)
TABLE_NAME = "memories"


def _db() -> lancedb.DBConnection:
    STORE_PATH.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(STORE_PATH))


def _get_table():
    db = _db()
    if TABLE_NAME not in db.table_names():
        return None
    return db.open_table(TABLE_NAME)


def init() -> None:
    STORE_PATH.mkdir(parents=True, exist_ok=True)
    _db()


class _UpsertingLanceDBVectorStore(LanceDBVectorStore):
    def add_documents(self, documents: list[Document], **kwargs: Any) -> list[str]:
        ids = kwargs.get("ids") or [doc.metadata.get("id") for doc in documents]
        if len(ids) != len(documents) or any(not id for id in ids):
            raise ValueError("Every LanceDB memory document must have an ID")

        table = _get_table()
        existing_rows: list[dict] = []
        if table:
            for id in ids:
                validate_memory_id(id)
                rows = table.search().where(f"id = '{id}'", prefilter=True).limit(1).to_list()
                if rows:
                    existing_rows.extend(deepcopy(rows))
                    table.delete(f"id = '{id}'")

        try:
            return super().add_documents(documents, **kwargs)
        except Exception:
            current_table = _get_table()
            if current_table and existing_rows:
                current_table.add(existing_rows)
            raise


def get_vectorstore(embeddings) -> VectorStore:
    return _UpsertingLanceDBVectorStore(
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
    rows = tbl.search().limit(int(limit) * 5).to_list()
    if repo:
        rows = [r for r in rows if r.get("metadata", {}).get("repo") == repo]
    return rows[:int(limit)]


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
