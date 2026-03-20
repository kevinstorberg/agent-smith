"""LanceDB + LangChain interface for agent long-term memory with time-weighted retrieval."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import lancedb
from langchain_community.vectorstores import LanceDB as LanceDBVectorStore
from langchain_core.documents import Document
from langchain_classic.retrievers.time_weighted_retriever import (
    TimeWeightedVectorStoreRetriever,
)
from langchain_huggingface import HuggingFaceEmbeddings

STORE_PATH = Path(__file__).parent.parent.parent / "memory_store"
MODEL_NAME = "all-MiniLM-L6-v2"
TABLE_NAME = "memories"
DECAY_RATE = float(os.environ.get("MEMORY_DECAY_RATE", "0.01"))

_embeddings: HuggingFaceEmbeddings | None = None
_retriever: TimeWeightedVectorStoreRetriever | None = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name=MODEL_NAME)
    return _embeddings


def _db() -> lancedb.DBConnection:
    STORE_PATH.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(STORE_PATH))


def _get_vectorstore() -> LanceDBVectorStore:
    return LanceDBVectorStore(
        connection=_db(),
        embedding=_get_embeddings(),
        table_name=TABLE_NAME,
        mode="append",
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(val) -> datetime:
    if isinstance(val, datetime):
        return val
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val)
    if isinstance(val, str) and val:
        try:
            return datetime.fromisoformat(val)
        except (ValueError, TypeError):
            pass
    return datetime.now()


def _get_retriever() -> TimeWeightedVectorStoreRetriever:
    """Build or return the cached time-weighted retriever."""
    global _retriever
    if _retriever is not None:
        return _retriever

    vectorstore = _get_vectorstore()

    _retriever = TimeWeightedVectorStoreRetriever(
        vectorstore=vectorstore,
        decay_rate=DECAY_RATE,
        k=10,
        search_kwargs={"k": 50},
    )

    # Load existing memories into memory_stream for time-weighting
    db = _db()
    if TABLE_NAME in db.table_names():
        tbl = db.open_table(TABLE_NAME)
        if tbl.count_rows() > 0:
            rows = tbl.search().limit(10000).to_list()
            for i, row in enumerate(rows):
                meta = row.get("metadata", {})
                doc = Document(
                    page_content=row.get("text", ""),
                    metadata={
                        **meta,
                        "last_accessed_at": _parse_datetime(meta.get("last_accessed_at")),
                        "buffer_idx": i,
                    },
                )
                _retriever.memory_stream.append(doc)

    return _retriever


def _meta_to_row(doc: Document) -> dict:
    meta = doc.metadata
    return {
        "id": meta.get("id", ""),
        "content": doc.page_content,
        "repo": meta.get("repo") or None,
        "tags": json.loads(meta.get("tags") or "[]"),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
    }


def _raw_to_row(record: dict) -> dict:
    meta = record.get("metadata", {})
    return {
        "id": record.get("id", meta.get("id", "")),
        "content": record.get("text", ""),
        "repo": meta.get("repo") or None,
        "tags": json.loads(meta.get("tags") or "[]"),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init() -> None:
    """Create the LanceDB store if it doesn't exist yet."""
    STORE_PATH.mkdir(parents=True, exist_ok=True)
    _db()


def add(content: str, repo: str | None = None, tags: list[str] | None = None) -> str:
    """Embed and store a memory. Returns the new memory ID."""
    assert content and content.strip(), "Memory content must not be empty."
    id = str(uuid.uuid4())
    now_str = _now()
    now_dt = datetime.now()

    doc = Document(
        page_content=content,
        metadata={
            "id": id,
            "repo": repo or "",
            "tags": json.dumps(tags or []),
            "created_at": now_str,
            "updated_at": now_str,
            "last_accessed_at": now_dt,
        },
    )

    retriever = _get_retriever()
    retriever.add_documents([doc], ids=[id], current_time=now_dt)
    return id


def search(query: str, repo: str | None = None, limit: int = 10) -> list[dict]:
    """Time-weighted semantic search. Returns ranked list of memories."""
    assert query and query.strip(), "Search query must not be empty."
    retriever = _get_retriever()

    if not retriever.memory_stream:
        return []

    retriever.k = limit
    docs = retriever.invoke(query)

    rows = []
    for doc in docs:
        if repo and doc.metadata.get("repo") != repo:
            continue
        rows.append(_meta_to_row(doc))

    return rows[:limit]


def list_memories(repo: str | None = None, limit: int = 20) -> list[dict]:
    """Return recent memories, newest first, optionally filtered by repo."""
    db = _db()
    if TABLE_NAME not in db.table_names():
        return []
    tbl = db.open_table(TABLE_NAME)
    if tbl.count_rows() == 0:
        return []

    rows = tbl.search().limit(limit).to_list()
    result = [_raw_to_row(r) for r in rows]
    if repo:
        result = [r for r in result if r.get("repo") == repo]
    result.sort(key=lambda r: r["created_at"] or "", reverse=True)
    return result[:limit]


def get(id: str) -> dict | None:
    """Fetch a single memory by ID. Returns None if not found."""
    assert id and id.strip(), "ID must not be empty."
    db = _db()
    if TABLE_NAME not in db.table_names():
        return None
    tbl = db.open_table(TABLE_NAME)
    results = tbl.search().where(f"id = '{id}'", prefilter=True).limit(1).to_list()
    return _raw_to_row(results[0]) if results else None


def delete(id: str) -> None:
    """Delete a memory by ID. Raises if not found."""
    assert id and id.strip(), "ID must not be empty."
    db = _db()
    if TABLE_NAME not in db.table_names():
        raise KeyError(f"Memory not found: {id}")
    tbl = db.open_table(TABLE_NAME)
    if not tbl.search().where(f"id = '{id}'", prefilter=True).limit(1).to_list():
        raise KeyError(f"Memory not found: {id}")
    tbl.delete(f"id = '{id}'")

    global _retriever
    if _retriever:
        _retriever.memory_stream = [
            doc for doc in _retriever.memory_stream
            if doc.metadata.get("id") != id
        ]
        for i, doc in enumerate(_retriever.memory_stream):
            doc.metadata["buffer_idx"] = i


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
    existing = get(id)
    if not existing:
        raise KeyError(f"Memory not found: {id}")

    new_content = content if content is not None else existing["content"]
    new_repo = repo if repo is not None else (existing.get("repo") or "")
    new_tags = tags if tags is not None else existing.get("tags", [])

    delete(id)
    now_str = _now()
    now_dt = datetime.now()

    doc = Document(
        page_content=new_content,
        metadata={
            "id": id,
            "repo": new_repo or "",
            "tags": json.dumps(new_tags),
            "created_at": existing.get("created_at", now_str),
            "updated_at": now_str,
            "last_accessed_at": now_dt,
        },
    )

    retriever = _get_retriever()
    retriever.add_documents([doc], ids=[id], current_time=now_dt)
