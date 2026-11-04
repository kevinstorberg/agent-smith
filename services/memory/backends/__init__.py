from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, TypedDict, cast

from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore

from scripts.shared.validation import validate_memory_id

TIMESTAMP_FIELDS = ("created_at", "updated_at", "last_accessed_at")


class BackendRow(TypedDict):
    id: str
    text: str
    metadata: dict[str, Any]


class MemoryBackend(Protocol):
    init: Callable[[], None]
    get_vectorstore: Callable[[Embeddings], VectorStore]
    load_all: Callable[[], list[BackendRow]]
    list_rows: Callable[[str | None, int], list[BackendRow]]
    get_row: Callable[[str], BackendRow | None]
    get_rows: Callable[[list[str]], list[BackendRow]]
    touch_accessed: Callable[[list[str], datetime], dict[str, str]]
    delete_row: Callable[[str], None]


def metadata_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Memory metadata {field!r} must be an ISO datetime") from exc
    else:
        raise ValueError(f"Memory metadata {field!r} must be a datetime")

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def memory_ids(ids: list[str]) -> list[str]:
    if not isinstance(ids, list) or any(not isinstance(id, str) for id in ids):
        raise ValueError("Memory IDs must be a list of UUID strings")
    for id in ids:
        validate_memory_id(id)
    return list(dict.fromkeys(id.lower() for id in ids))


def access_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Memory accessed_at must be a timezone-aware datetime")
    return metadata_datetime(value, "accessed_at")


def canonical_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    result = dict(metadata)
    for field in TIMESTAMP_FIELDS:
        if result.get(field) is not None:
            result[field] = metadata_datetime(result[field], field).isoformat()
    return result


def get_backend() -> MemoryBackend:
    name = os.environ.get("MEMORY_BACKEND", "lancedb")

    if name == "lancedb":
        from services.memory.backends import lancedb_backend
        return cast(MemoryBackend, lancedb_backend)
    elif name == "pinecone":
        from services.memory.backends import pinecone_backend
        return cast(MemoryBackend, pinecone_backend)
    elif name == "pgvector":
        from services.memory.backends import pgvector_backend
        return cast(MemoryBackend, pgvector_backend)
    else:
        raise ValueError(
            f"Unknown memory backend: {name!r}; expected lancedb, pinecone, or pgvector"
        )


def build_row(id: str, text: str, metadata: dict[str, Any]) -> BackendRow:
    return {"id": id, "text": text, "metadata": canonical_metadata(metadata)}
