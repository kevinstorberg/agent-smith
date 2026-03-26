from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

from langchain_core.documents import Document
from langchain_classic.retrievers.time_weighted_retriever import (
    TimeWeightedVectorStoreRetriever,
)
from langchain_huggingface import HuggingFaceEmbeddings

from services.memory.backends import get_backend

MODEL_NAME = os.environ.get("MEMORY_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
DECAY_RATE = float(os.environ.get("MEMORY_DECAY_RATE", "0.01"))
DEFAULT_LIMIT = int(os.environ.get("MEMORY_DEFAULT_LIMIT", "20"))

_embeddings: HuggingFaceEmbeddings | None = None
_retriever: TimeWeightedVectorStoreRetriever | None = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name=MODEL_NAME)
    return _embeddings


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
    global _retriever
    if _retriever is not None:
        return _retriever

    backend = get_backend()
    vectorstore = backend.get_vectorstore(_get_embeddings())

    _retriever = TimeWeightedVectorStoreRetriever(
        vectorstore=vectorstore,
        decay_rate=DECAY_RATE,
        k=10,
        search_kwargs={"k": 50},
    )

    rows = backend.load_all()
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


def _to_row(*, content: str, id: str, meta: dict) -> dict:
    return {
        "id": id,
        "content": content,
        "repo": meta.get("repo") or None,
        "tags": json.loads(meta.get("tags") or "[]"),
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
    }


def _doc_to_row(doc: Document) -> dict:
    return _to_row(content=doc.page_content, id=doc.metadata.get("id", ""), meta=doc.metadata)


def _raw_to_row(record: dict) -> dict:
    meta = record.get("metadata", {})
    return _to_row(content=record.get("text", ""), id=record.get("id", meta.get("id", "")), meta=meta)



def init() -> None:
    get_backend().init()


def add(content: str, repo: str | None = None, tags: list[str] | None = None) -> str:
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
        },
    )

    retriever = _get_retriever()
    retriever.add_documents([doc], ids=[id], current_time=now_dt)
    return id


def search(query: str, repo: str | None = None, limit: int = DEFAULT_LIMIT) -> list[dict]:
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
        rows.append(_doc_to_row(doc))

    return rows[:limit]


def list_memories(repo: str | None = None, limit: int = DEFAULT_LIMIT) -> list[dict]:
    backend = get_backend()
    rows = backend.list_rows(repo=repo, limit=limit)
    result = [_raw_to_row(r) for r in rows]
    result.sort(key=lambda r: r["created_at"] or "", reverse=True)
    return result[:limit]


def get(id: str) -> dict | None:
    assert id and id.strip(), "ID must not be empty."
    row = get_backend().get_row(id)
    return _raw_to_row(row) if row else None


def delete(id: str) -> None:
    assert id and id.strip(), "ID must not be empty."
    get_backend().delete_row(id)

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
        },
    )

    retriever = _get_retriever()
    retriever.add_documents([doc], ids=[id], current_time=now_dt)
