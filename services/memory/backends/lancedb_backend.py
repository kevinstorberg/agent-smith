from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

import lancedb
import pyarrow as pa
from langchain_core.vectorstores import VectorStore
from langchain_community.vectorstores import LanceDB as LanceDBVectorStore
from langchain_core.documents import Document

from scripts.shared.validation import validate_memory_id
from services.config import MEMORY_STORE_PATH
from services.memory.backends import (
    TIMESTAMP_FIELDS, access_datetime, build_row, canonical_metadata, memory_ids, metadata_datetime,
)

STORE_PATH = Path(MEMORY_STORE_PATH)
TABLE_NAME = "memories"
_schema_lock = Lock()
_write_lock = Lock()


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


def _prepare_table():
    with _schema_lock:
        table = _get_table()
        if table is not None:
            metadata_type = table.schema.field("metadata").type
            missing = [pa.field(name, pa.string()) for name in ("source_type", "source_id") if name not in metadata_type.names]
            if missing:
                table.add_columns(pa.schema([pa.field("metadata", pa.struct(missing))]))
        return table


class _UpsertingLanceDBVectorStore(LanceDBVectorStore):
    def similarity_search_with_score(self, query: str, k: int = 4, **kwargs: Any) -> list[tuple[Document, float]]:
        if _get_table() is None:
            return []
        return super().similarity_search_with_score(query, k=k, **kwargs)

    def similarity_search(self, query: str, k: int = 4, **kwargs: Any) -> list[Document]:
        if _get_table() is None:
            return []
        return super().similarity_search(query, k=k, **kwargs)

    def add_documents(self, documents: list[Document], **kwargs: Any) -> list[str]:
        with _write_lock:
            return self._add_documents(documents, **kwargs)

    def _add_documents(self, documents: list[Document], **kwargs: Any) -> list[str]:
        ids = memory_ids(kwargs.get("ids") or [doc.metadata.get("id") for doc in documents])
        if len(ids) != len(documents):
            raise ValueError("Every LanceDB memory document must have one unique UUID")
        kwargs["ids"] = ids
        sanitized = deepcopy(documents)
        for document in sanitized:
            document.metadata = canonical_metadata(document.metadata)
        table = _prepare_table()
        metadata_type = table.schema.field("metadata").type if table is not None else None
        for document in sanitized:
            for field in TIMESTAMP_FIELDS:
                if document.metadata.get(field) is None:
                    continue
                field_type = metadata_type.field(field).type if metadata_type is not None and field in metadata_type.names else None
                if (field_type is not None and pa.types.is_timestamp(field_type)) or (table is None and field == "last_accessed_at"):
                    document.metadata[field] = metadata_datetime(document.metadata[field], field)
        existing_rows: list[dict] = []
        if table:
            for id, document in zip(ids, sanitized, strict=True):
                validate_memory_id(id)
                rows = table.search().where(f"id = '{id}'", prefilter=True).limit(1).to_list()
                if rows:
                    existing_rows.extend(deepcopy(rows))
                    old_access = rows[0].get("metadata", {}).get("last_accessed_at")
                    new_access = document.metadata.get("last_accessed_at")
                    if old_access is not None:
                        latest = metadata_datetime(old_access, "last_accessed_at")
                        if new_access is not None:
                            latest = max(latest, metadata_datetime(new_access, "last_accessed_at"))
                        access_type = metadata_type.field("last_accessed_at").type
                        document.metadata["last_accessed_at"] = latest if pa.types.is_timestamp(access_type) else latest.isoformat()
                    table.delete(f"id = '{id}'")

        try:
            return super().add_documents(sanitized, **kwargs)
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
    return _canonical_rows(tbl.search().limit(10000).to_list())


def list_rows(repo: str | None = None, limit: int = 20) -> list[dict]:
    tbl = _get_table()
    if not tbl or tbl.count_rows() == 0:
        return []
    rows = tbl.search().limit(int(limit) * 5).to_list()
    if repo:
        rows = [r for r in rows if r.get("metadata", {}).get("repo") == repo]
    return _canonical_rows(rows[:int(limit)])


def _canonical_rows(rows: list[dict]) -> list[dict]:
    return [build_row(row["id"], row.get("text", ""), row.get("metadata", {})) for row in rows]


def get_row(id: str) -> dict | None:
    rows = get_rows([id])
    return rows[0] if rows else None


def get_rows(ids: list[str]) -> list[dict]:
    ids = memory_ids(ids)
    if not ids:
        return []
    tbl = _get_table()
    if not tbl:
        return []
    rows = {row["id"]: row for row in _canonical_rows(tbl.search().where(_ids_filter(ids), prefilter=True).limit(len(ids)).to_list())}
    return [rows[id] for id in ids if id in rows]


def _ids_filter(ids: list[str]) -> str:
    return "id IN (" + ", ".join(f"'{id}'" for id in ids) + ")"


def touch_accessed(ids: list[str], accessed_at: datetime) -> dict[str, str]:
    ids, stamp = memory_ids(ids), access_datetime(accessed_at)
    if not ids:
        return {}
    with _write_lock:
        return _touch_accessed(ids, stamp)


def _touch_accessed(ids: list[str], stamp: datetime) -> dict[str, str]:
    table = _get_table()
    if table is None:
        return {}
    with _schema_lock:
        metadata_type = table.schema.field("metadata").type
        if "last_accessed_at" not in metadata_type.names:
            table.add_columns(pa.schema([pa.field("metadata", pa.struct([pa.field("last_accessed_at", pa.string())]))]))
        elif pa.types.is_null(metadata_type.field("last_accessed_at").type):
            raise ValueError("LanceDB memory last_accessed_at has a null-only schema; migrate it to a timestamp or ISO string column")
        metadata_type = table.schema.field("metadata").type
    field_type = metadata_type.field("last_accessed_at").type
    if not (pa.types.is_timestamp(field_type) or pa.types.is_string(field_type) or pa.types.is_large_string(field_type)):
        raise ValueError("LanceDB memory last_accessed_at must be a timestamp or ISO string column")
    latest = f"GREATEST(CAST(metadata.last_accessed_at AS TIMESTAMP), TIMESTAMP '{stamp.isoformat()}')"
    if not pa.types.is_timestamp(field_type):
        latest = f"to_char({latest}, '%Y-%m-%dT%H:%M:%S%.6f+00:00')"
    fields = []
    for field in metadata_type:
        key = "'" + field.name.replace("'", "''") + "'"
        value = latest if field.name == "last_accessed_at" else f"get_field(metadata, {key})"
        fields.extend((key, value))
    # Nested assignments are unsupported; current-row expressions preserve sibling metadata.
    table.update(where=_ids_filter(ids), values_sql={"metadata": "named_struct(" + ", ".join(fields) + ")"})
    return {row["id"]: row["metadata"]["last_accessed_at"] for row in get_rows(ids)}


def delete_row(id: str) -> None:
    validate_memory_id(id)
    with _write_lock:
        _delete_row(id)


def _delete_row(id: str) -> None:
    tbl = _get_table()
    if not tbl:
        raise KeyError(f"Memory not found: {id}")
    if not tbl.search().where(f"id = '{id}'", prefilter=True).limit(1).to_list():
        raise KeyError(f"Memory not found: {id}")
    tbl.delete(f"id = '{id}'")
