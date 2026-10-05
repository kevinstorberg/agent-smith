from __future__ import annotations

import json
import math
import threading
import uuid
from datetime import datetime, timezone
from numbers import Real
from typing import Any, Iterable

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore
from pgvector import Vector
from pgvector.psycopg2 import register_vector

from scripts.shared.validation import validate_memory_id
from services.config import MEMORY_EMBEDDING_DIMENSION, MEMORY_EMBEDDING_MODEL
from services.db import get_connection
from services.memory.backends import BackendRow, build_row

TABLE_NAME = "memories"

_init_lock = threading.Lock()
_initialized = False


def _as_utc(value: Any, field: str) -> datetime:
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


def _parse_tags(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Memory metadata 'tags' must be a JSON string array") from exc
    if not isinstance(value, list) or any(not isinstance(tag, str) for tag in value):
        raise ValueError("Memory metadata 'tags' must be a list of strings")
    return value


def _validated_vector(values: Iterable[Real], boundary: str) -> Vector:
    vector = list(values)
    if len(vector) != MEMORY_EMBEDDING_DIMENSION:
        raise ValueError(
            f"{boundary} returned {len(vector)} dimensions; "
            f"MEMORY_EMBEDDING_DIMENSION requires {MEMORY_EMBEDDING_DIMENSION}"
        )
    if any(isinstance(value, bool) or not isinstance(value, Real) for value in vector):
        raise ValueError(f"{boundary} returned a non-numeric embedding value")
    if any(not math.isfinite(float(value)) for value in vector):
        raise ValueError(f"{boundary} returned a non-finite embedding value")
    return Vector([float(value) for value in vector])


def _metadata_values(id: str, metadata: dict[str, Any]) -> tuple[Any, ...]:
    metadata_id = metadata.get("id")
    if metadata_id not in (None, id):
        raise ValueError(
            f"Document metadata ID {metadata_id!r} does not match requested ID {id!r}"
        )
    repo = metadata.get("repo") or None
    if repo is not None and not isinstance(repo, str):
        raise ValueError("Memory metadata 'repo' must be a string or null")
    return (
        uuid.UUID(id),
        repo,
        _parse_tags(metadata.get("tags", [])),
        _as_utc(metadata.get("created_at"), "created_at"),
        _as_utc(metadata.get("updated_at"), "updated_at"),
        _as_utc(metadata.get("last_accessed_at"), "last_accessed_at"),
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _to_backend_row(row: tuple[Any, ...]) -> BackendRow:
    id, content, repo, tags, created_at, updated_at, last_accessed_at = row
    metadata = {
        "id": str(id),
        "repo": repo or "",
        "tags": json.dumps(tags),
        "created_at": _iso(created_at),
        "updated_at": _iso(updated_at),
        "last_accessed_at": _iso(last_accessed_at),
    }
    return build_row(str(id), content, metadata)


def _validate_database_contract(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        if cur.fetchone() is None:
            raise RuntimeError(
                "PostgreSQL extension 'vector' is not installed; run database migrations"
            )
        cur.execute(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute AS a
            WHERE a.attrelid = 'memories'::regclass
              AND a.attname = 'embedding'
              AND NOT a.attisdropped
            """
        )
        embedding_type = cur.fetchone()
        expected_type = f"vector({MEMORY_EMBEDDING_DIMENSION})"
        if embedding_type != (expected_type,):
            actual = embedding_type[0] if embedding_type else "missing"
            raise RuntimeError(
                f"memories.embedding is {actual}; expected {expected_type}"
            )
        cur.execute("SELECT DISTINCT embedding_model FROM memories LIMIT 2")
        models = {row[0] for row in cur.fetchall()}
        if models and models != {MEMORY_EMBEDDING_MODEL}:
            raise RuntimeError(
                "memories contains embedding models incompatible with "
                f"MEMORY_EMBEDDING_MODEL={MEMORY_EMBEDDING_MODEL!r}: {sorted(models)}"
            )


def init() -> None:
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        with get_connection() as conn:
            _validate_database_contract(conn)
            register_vector(conn, globally=True, arrays=False)
        _initialized = True


class PGVectorStore(VectorStore):
    def __init__(self, embedding: Embeddings):
        self._embedding = embedding

    @property
    def embeddings(self) -> Embeddings:
        return self._embedding

    def add_texts(
        self,
        texts: Iterable[str],
        metadatas: list[dict[str, Any]] | None = None,
        *,
        ids: list[str] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        del kwargs
        text_list = list(texts)
        if not text_list or any(not text.strip() for text in text_list):
            raise ValueError("Memory content must not be empty")
        if ids is None or len(ids) != len(text_list):
            raise ValueError("Every pgvector memory document must have exactly one ID")
        if metadatas is None or len(metadatas) != len(text_list):
            raise ValueError("Every pgvector memory document must have metadata")
        for id in ids:
            validate_memory_id(id)

        embeddings = self._embedding.embed_documents(text_list)
        if len(embeddings) != len(text_list):
            raise ValueError(
                "Embedding provider returned a different number of vectors than documents"
            )

        records = []
        for id, content, metadata, embedding in zip(
            ids, text_list, metadatas, embeddings, strict=True
        ):
            row_id, repo, tags, created_at, updated_at, last_accessed_at = (
                _metadata_values(id, metadata)
            )
            records.append(
                (
                    row_id,
                    content,
                    repo,
                    tags,
                    _validated_vector(embedding, "Embedding provider"),
                    MEMORY_EMBEDDING_MODEL,
                    created_at,
                    updated_at,
                    last_accessed_at,
                )
            )

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO memories (
                        id, content, repo, tags, embedding, embedding_model,
                        created_at, updated_at, last_accessed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        repo = EXCLUDED.repo,
                        tags = EXCLUDED.tags,
                        embedding = EXCLUDED.embedding,
                        embedding_model = EXCLUDED.embedding_model,
                        updated_at = EXCLUDED.updated_at,
                        last_accessed_at = EXCLUDED.last_accessed_at
                    """,
                    records,
                )
        return ids

    def similarity_search_with_score(
        self, query: str, k: int = 4, **kwargs: Any
    ) -> list[tuple[Document, float]]:
        del kwargs
        if not query.strip():
            raise ValueError("Search query must not be empty")
        if k <= 0:
            raise ValueError("Search result limit must be positive")
        query_vector = _validated_vector(
            self._embedding.embed_query(query), "Embedding provider"
        )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, content, repo, tags, created_at, updated_at,
                           last_accessed_at, embedding <=> %s AS distance
                    FROM memories
                    WHERE embedding_model = %s
                    ORDER BY embedding <=> %s, id
                    LIMIT %s
                    """,
                    (query_vector, MEMORY_EMBEDDING_MODEL, query_vector, int(k)),
                )
                rows = cur.fetchall()
        return [
            (
                Document(
                    page_content=row[1],
                    metadata=_to_backend_row(row[:7])["metadata"],
                ),
                float(row[7]),
            )
            for row in rows
        ]

    def similarity_search(
        self, query: str, k: int = 4, **kwargs: Any
    ) -> list[Document]:
        return [doc for doc, _ in self.similarity_search_with_score(query, k, **kwargs)]

    def _select_relevance_score_fn(self):
        return self._cosine_relevance_score_fn

    @classmethod
    def from_texts(
        cls,
        texts: list[str],
        embedding: Embeddings,
        metadatas: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> "PGVectorStore":
        ids = kwargs.pop("ids", None)
        store = cls(embedding)
        store.add_texts(texts, metadatas, ids=ids, **kwargs)
        return store


def get_vectorstore(embeddings: Embeddings) -> VectorStore:
    init()
    return PGVectorStore(embeddings)


def load_all() -> list[BackendRow]:
    init()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content, repo, tags, created_at, updated_at, last_accessed_at
                FROM memories
                ORDER BY created_at, id
                """
            )
            return [_to_backend_row(row) for row in cur.fetchall()]


def list_rows(repo: str | None = None, limit: int = 20) -> list[BackendRow]:
    init()
    if limit <= 0:
        raise ValueError("Memory row limit must be positive")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content, repo, tags, created_at, updated_at, last_accessed_at
                FROM memories
                WHERE (%s IS NULL OR repo = %s)
                ORDER BY created_at DESC, id
                LIMIT %s
                """,
                (repo, repo, int(limit)),
            )
            return [_to_backend_row(row) for row in cur.fetchall()]


def get_row(id: str) -> BackendRow | None:
    validate_memory_id(id)
    init()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content, repo, tags, created_at, updated_at, last_accessed_at
                FROM memories
                WHERE id = %s
                """,
                (uuid.UUID(id),),
            )
            row = cur.fetchone()
    return _to_backend_row(row) if row else None


def delete_row(id: str) -> None:
    validate_memory_id(id)
    init()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM memories WHERE id = %s", (uuid.UUID(id),))
            if cur.rowcount != 1:
                raise KeyError(f"Memory not found: {id}")
