from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec

from scripts.shared.validation import validate_memory_id
from services.config import PINECONE_INDEX as INDEX_NAME, PINECONE_CLOUD as CLOUD, PINECONE_REGION as REGION
from services.memory.backends import build_row
DIMENSION = 384  # all-MiniLM-L6-v2

_pc: Pinecone | None = None
_index = None


def _get_pc() -> Pinecone:
    global _pc
    if _pc is None:
        api_key = os.environ.get("PINECONE_API_KEY")
        assert api_key, "PINECONE_API_KEY must be set when using pinecone backend."
        _pc = Pinecone(api_key=api_key)
    return _pc


def _get_index():
    global _index
    if _index is None:
        pc = _get_pc()
        if not pc.has_index(INDEX_NAME):
            pc.create_index(
                name=INDEX_NAME,
                dimension=DIMENSION,
                metric="cosine",
                spec=ServerlessSpec(cloud=CLOUD, region=REGION),
            )
            while not pc.describe_index(INDEX_NAME).status["ready"]:
                time.sleep(1)
        _index = pc.Index(INDEX_NAME)
    return _index


def init() -> None:
    _get_index()


class _SafePineconeVectorStore(PineconeVectorStore):

    def add_documents(self, documents: list[Document], **kwargs: Any) -> list[str]:
        for doc in documents:
            for key, val in list(doc.metadata.items()):
                if isinstance(val, datetime):
                    doc.metadata[key] = val.isoformat()
        kwargs.pop("current_time", None)
        return super().add_documents(documents, **kwargs)


def get_vectorstore(embeddings) -> VectorStore:
    return _SafePineconeVectorStore(index=_get_index(), embedding=embeddings)


def count() -> int:
    stats = _get_index().describe_index_stats()
    return stats.get("total_vector_count", 0)


def load_all() -> list[dict]:
    index = _get_index()
    total = count()
    if total == 0:
        return []

    dummy_vec = [0.0] * DIMENSION
    results = index.query(vector=dummy_vec, top_k=min(total, 10000), include_metadata=True)
    rows = []
    for match in results.get("matches", []):
        meta = dict(match.get("metadata", {}))
        text = meta.pop("text", "")
        rows.append(build_row(match["id"], text, meta))
    return rows


def list_rows(repo: str | None = None, limit: int = 20) -> list[dict]:
    rows = load_all()
    if repo:
        rows = [r for r in rows if r.get("metadata", {}).get("repo") == repo]
    return rows[:limit]


def _fetch_vectors(result) -> dict:
    if hasattr(result, "vectors"):
        return result.vectors or {}
    return result.get("vectors", {})


def get_row(id: str) -> dict | None:
    validate_memory_id(id)
    vectors = _fetch_vectors(_get_index().fetch(ids=[id]))
    if id not in vectors:
        return None
    vec_data = vectors[id]
    meta = dict(getattr(vec_data, "metadata", None) or vec_data.get("metadata", {}))
    text = meta.pop("text", "")
    return build_row(id, text, meta)


def delete_row(id: str) -> None:
    validate_memory_id(id)
    vectors = _fetch_vectors(_get_index().fetch(ids=[id]))
    if id not in vectors:
        raise KeyError(f"Memory not found: {id}")
    _get_index().delete(ids=[id])
