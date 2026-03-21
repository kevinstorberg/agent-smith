"""Pinecone backend for agent memory (cloud vector store)."""

from __future__ import annotations

import os
import re
import time

from langchain_core.vectorstores import VectorStore
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec

INDEX_NAME = os.environ.get("PINECONE_INDEX", "agent-smith-memories")
CLOUD = os.environ.get("PINECONE_CLOUD", "aws")
REGION = os.environ.get("PINECONE_REGION", "us-east-1")
DIMENSION = 384  # all-MiniLM-L6-v2
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

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
    """Ensure the Pinecone index exists."""
    _get_index()


def get_vectorstore(embeddings) -> VectorStore:
    return PineconeVectorStore(index=_get_index(), embedding=embeddings)


def count() -> int:
    stats = _get_index().describe_index_stats()
    return stats.get("total_vector_count", 0)


def load_all() -> list[dict]:
    """Fetch all vectors for populating the retriever memory_stream."""
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
        rows.append({"id": match["id"], "text": text, "metadata": meta})
    return rows


def list_rows(repo: str | None = None, limit: int = 20) -> list[dict]:
    rows = load_all()
    if repo:
        rows = [r for r in rows if r.get("metadata", {}).get("repo") == repo]
    return rows[:limit]


def _validate_id(id: str) -> None:
    if not _UUID_RE.match(id):
        raise ValueError(f"Invalid memory ID format: {id}")


def get_row(id: str) -> dict | None:
    _validate_id(id)
    result = _get_index().fetch(ids=[id])
    vectors = result.get("vectors", {})
    if id not in vectors:
        return None
    vec_data = vectors[id]
    meta = dict(vec_data.get("metadata", {}))
    text = meta.pop("text", "")
    return {"id": id, "text": text, "metadata": meta}


def delete_row(id: str) -> None:
    _validate_id(id)
    result = _get_index().fetch(ids=[id])
    if id not in result.get("vectors", {}):
        raise KeyError(f"Memory not found: {id}")
    _get_index().delete(ids=[id])
