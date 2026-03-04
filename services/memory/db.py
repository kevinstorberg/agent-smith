"""LanceDB interface for agent long-term memory."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa
from sentence_transformers import SentenceTransformer

STORE_PATH = Path(__file__).parent.parent.parent / "memory_store"
MODEL_NAME = "all-MiniLM-L6-v2"
VECTOR_DIM = 384
TABLE_NAME = "memories"

_model: SentenceTransformer | None = None


def _embed_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def _embed(text: str) -> list[float]:
    return _embed_model().encode(text, normalize_embeddings=True).tolist()


def _db() -> lancedb.DBConnection:
    STORE_PATH.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(STORE_PATH))


def _table() -> lancedb.table.Table:
    db = _db()
    if TABLE_NAME in db.table_names():
        return db.open_table(TABLE_NAME)

    schema = pa.schema([
        pa.field("id", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), VECTOR_DIM)),
        pa.field("content", pa.string()),
        pa.field("repo", pa.string()),
        pa.field("tags", pa.string()),       # JSON array string
        pa.field("created_at", pa.string()),
        pa.field("updated_at", pa.string()),
    ])
    return db.create_table(TABLE_NAME, schema=schema)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(record: dict) -> dict:
    return {
        "id": record["id"],
        "content": record["content"],
        "repo": record.get("repo") or None,
        "tags": json.loads(record.get("tags") or "[]"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init() -> None:
    """Create the LanceDB store and table if they don't exist yet."""
    _table()  # creates table if missing


def add(content: str, repo: str | None = None, tags: list[str] | None = None) -> str:
    """Embed and store a memory. Returns the new memory ID."""
    assert content and content.strip(), "Memory content must not be empty."
    id = str(uuid.uuid4())
    now = _now()
    _table().add([{
        "id": id,
        "vector": _embed(content),
        "content": content,
        "repo": repo or "",
        "tags": json.dumps(tags or []),
        "created_at": now,
        "updated_at": now,
    }])
    return id


def search(query: str, repo: str | None = None, limit: int = 10) -> list[dict]:
    """Semantic similarity search. Returns ranked list of memories."""
    assert query and query.strip(), "Search query must not be empty."
    tbl = _table()
    if tbl.count_rows() == 0:
        return []

    q = tbl.search(_embed(query)).metric("cosine").limit(limit).select(
        ["id", "content", "repo", "tags", "created_at", "updated_at", "_distance"]
    )
    if repo:
        q = q.where(f"repo = '{repo}'", prefilter=True)

    results = q.to_list()
    rows = []
    for r in results:
        row = _row(r)
        row["score"] = round(1 - r.get("_distance", 0), 4)
        rows.append(row)
    return rows


def list_memories(repo: str | None = None, limit: int = 20) -> list[dict]:
    """Return recent memories, newest first, optionally filtered by repo."""
    tbl = _table()
    if tbl.count_rows() == 0:
        return []

    q = tbl.search().select(
        ["id", "content", "repo", "tags", "created_at", "updated_at"]
    ).limit(limit)
    if repo:
        q = q.where(f"repo = '{repo}'", prefilter=True)

    results = q.to_list()
    rows = [_row(r) for r in results]
    rows.sort(key=lambda r: r["created_at"] or "", reverse=True)
    return rows


def get(id: str) -> dict | None:
    """Fetch a single memory by ID. Returns None if not found."""
    assert id and id.strip(), "ID must not be empty."
    tbl = _table()
    results = tbl.search().where(f"id = '{id}'", prefilter=True).select(
        ["id", "content", "repo", "tags", "created_at", "updated_at"]
    ).limit(1).to_list()
    return _row(results[0]) if results else None


def delete(id: str) -> None:
    """Delete a memory by ID. Raises if not found."""
    assert id and id.strip(), "ID must not be empty."
    tbl = _table()
    if not tbl.search().where(f"id = '{id}'", prefilter=True).limit(1).to_list():
        raise KeyError(f"Memory not found: {id}")
    tbl.delete(f"id = '{id}'")


def update(
    id: str,
    content: str | None = None,
    repo: str | None = None,
    tags: list[str] | None = None,
) -> None:
    """Patch an existing memory. Re-embeds if content changes."""
    assert id and id.strip(), "ID must not be empty."
    assert any(v is not None for v in (content, repo, tags)), (
        "Provide at least one of: content, repo, tags."
    )
    tbl = _table()
    existing = tbl.search().where(f"id = '{id}'", prefilter=True).select(
        ["id", "content", "repo", "tags", "created_at", "updated_at"]
    ).limit(1).to_list()
    if not existing:
        raise KeyError(f"Memory not found: {id}")

    old = existing[0]
    new_content = content if content is not None else old["content"]
    new_repo = (repo if repo is not None else old.get("repo")) or ""
    new_tags = json.dumps(tags if tags is not None else json.loads(old.get("tags") or "[]"))

    tbl.delete(f"id = '{id}'")
    tbl.add([{
        "id": id,
        "vector": _embed(new_content),
        "content": new_content,
        "repo": new_repo,
        "tags": new_tags,
        "created_at": old.get("created_at", _now()),
        "updated_at": _now(),
    }])
