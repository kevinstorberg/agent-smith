from __future__ import annotations

import os
from typing import Any, Callable, Protocol, TypedDict, cast

from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore


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
    delete_row: Callable[[str], None]


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
    return {"id": id, "text": text, "metadata": dict(metadata)}
