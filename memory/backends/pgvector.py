import json
import math
import re

from sqlalchemy import text as sql_text

from config.loader import load_default_config
from memory.base import MemoryBackend

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_identifier(value: str, *, field: str) -> str:
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(f"{field} must be a simple SQL identifier, got {value!r}")
    return value


def _vector_literal(embedding: list[float], dimension: int) -> str:
    if len(embedding) != dimension:
        raise ValueError(f"Embedding dimension mismatch: expected {dimension}, got {len(embedding)}")
    values = []
    for value in embedding:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"Embedding values must be finite, got {value!r}")
        values.append(str(number))
    return "[" + ",".join(values) + "]"


def _metadata_to_dict(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return json.loads(value)


class PGVectorBackend(MemoryBackend):
    def __init__(self, *, session_factory=None, table_name: str | None = None, dimension: int | None = None):
        config = load_default_config().memory
        self._session_factory = session_factory
        self._table_name = _validate_identifier(table_name or config.pgvector_table, field="pgvector_table")
        self._dimension = dimension or config.embedding_dimension
        self._schema_ready = False

    @property
    def table_name(self) -> str:
        return self._table_name

    def _get_session_factory(self):
        if self._session_factory is None:
            from db.connection import get_session_factory

            self._session_factory = get_session_factory()
        return self._session_factory

    async def _ensure_schema(self, session) -> None:
        if self._schema_ready:
            return
        await session.execute(sql_text("CREATE EXTENSION IF NOT EXISTS vector"))
        await session.execute(
            sql_text(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table_name} (
                    id text PRIMARY KEY,
                    text text NOT NULL,
                    metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    embedding vector({self._dimension}) NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
        )
        self._schema_ready = True

    async def store(self, id: str, text: str, metadata: dict, embedding: list[float]) -> None:
        embedding_value = _vector_literal(embedding, self._dimension)
        metadata_value = json.dumps(metadata)
        session_factory = self._get_session_factory()
        async with session_factory() as session:
            async with session.begin():
                await self._ensure_schema(session)
                await session.execute(
                    sql_text(
                        f"""
                        INSERT INTO {self._table_name} (id, text, metadata, embedding, updated_at)
                        VALUES (:id, :text, CAST(:metadata AS jsonb), CAST(:embedding AS vector), now())
                        ON CONFLICT (id) DO UPDATE SET
                            text = EXCLUDED.text,
                            metadata = EXCLUDED.metadata,
                            embedding = EXCLUDED.embedding,
                            updated_at = now()
                        """
                    ),
                    {"id": id, "text": text, "metadata": metadata_value, "embedding": embedding_value},
                )

    async def search(self, query_embedding: list[float], limit: int = 10, filters: dict | None = None) -> list[dict]:
        embedding_value = _vector_literal(query_embedding, self._dimension)
        params = {"embedding": embedding_value, "limit": limit}
        where_clause = ""
        if filters:
            where_clause = "WHERE metadata @> CAST(:filters AS jsonb)"
            params["filters"] = json.dumps(filters)

        session_factory = self._get_session_factory()
        async with session_factory() as session:
            async with session.begin():
                await self._ensure_schema(session)
                result = await session.execute(
                    sql_text(
                        f"""
                        SELECT
                            id,
                            text,
                            metadata,
                            1 - (embedding <=> CAST(:embedding AS vector)) AS score
                        FROM {self._table_name}
                        {where_clause}
                        ORDER BY embedding <=> CAST(:embedding AS vector)
                        LIMIT :limit
                        """
                    ),
                    params,
                )
                rows = list(result)

        return [
            {
                "id": row.id,
                "text": row.text,
                "metadata": _metadata_to_dict(row.metadata),
                "score": float(row.score),
            }
            for row in rows
        ]

    async def delete(self, id: str) -> None:
        session_factory = self._get_session_factory()
        async with session_factory() as session:
            async with session.begin():
                await self._ensure_schema(session)
                await session.execute(sql_text(f"DELETE FROM {self._table_name} WHERE id = :id"), {"id": id})
