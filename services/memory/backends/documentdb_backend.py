from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langchain_community.vectorstores.documentdb import (
    DocumentDBSimilarityType,
    DocumentDBVectorSearch,
)
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore
from pymongo import MongoClient

from scripts.shared.validation import validate_memory_id
from services.memory.similarity import cosine_similarity

URI = os.environ.get("DOCUMENTDB_URI", "")
DATABASE = os.environ.get("DOCUMENTDB_DATABASE", "agent_smith")
COLLECTION = os.environ.get("DOCUMENTDB_COLLECTION", "memories")
INDEX_NAME = os.environ.get("DOCUMENTDB_INDEX_NAME", "vectorSearchIndex")
TLS_CA_FILE = os.environ.get("DOCUMENTDB_TLS_CA_FILE", "")

TEXT_KEY = "textContent"
EMBEDDING_KEY = "vectorContent"

_client: MongoClient | None = None
_collection = None


def _get_client() -> MongoClient:
    global _client
    if _client is not None:
        return _client

    assert URI, "DOCUMENTDB_URI must be set when using documentdb backend."
    assert URI.startswith(("mongodb://", "mongodb+srv://")), (
        f"DOCUMENTDB_URI must be a mongodb:// URL, got: {URI[:20]}..."
    )

    kwargs: dict[str, Any] = {"tls": True, "retryWrites": False}
    if TLS_CA_FILE:
        assert Path(TLS_CA_FILE).exists(), f"TLS CA file not found: {TLS_CA_FILE}"
        kwargs["tlsCAFile"] = TLS_CA_FILE

    _client = MongoClient(URI, **kwargs)
    _client.admin.command("hello")
    return _client


def _get_collection():
    global _collection
    if _collection is not None:
        return _collection
    client = _get_client()
    _collection = client[DATABASE][COLLECTION]
    return _collection


def _embedding_dimensions() -> int:
    from services.memory.db import _get_embeddings
    sample = _get_embeddings().embed_query("dimension probe")
    return len(sample)


class ScoredDocDBVectorSearch(DocumentDBVectorSearch):

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        ef_search: int = 40,
        **kwargs: Any,
    ) -> list[tuple[Document, float]]:
        query_embedding = self._embedding.embed_query(query)

        pipeline: list[dict[str, Any]] = [
            {
                "$search": {
                    "vectorSearch": {
                        "vector": query_embedding,
                        "path": self._embedding_key,
                        "similarity": self._similarity_type,
                        "k": k,
                        "efSearch": ef_search,
                    }
                }
            }
        ]

        results = []
        for res in self._collection.aggregate(pipeline):
            doc_embedding = res.pop(self._embedding_key, None)
            text = res.pop(self._text_key, "")
            res.pop("_id", None)
            doc = Document(page_content=text, metadata=res)

            score = cosine_similarity(query_embedding, doc_embedding) if doc_embedding else 0.0
            results.append((doc, score))

        return results


def init() -> None:
    collection = _get_collection()
    collection.create_index("id", unique=True, name="id_unique")

    store = ScoredDocDBVectorSearch(
        collection=collection,
        embedding=_lazy_embeddings(),
        index_name=INDEX_NAME,
    )
    if not store.index_exists():
        dims = _embedding_dimensions()
        store.create_index(
            dimensions=dims,
            similarity=DocumentDBSimilarityType.COS,
            m=16,
            ef_construction=64,
        )


class _LazyEmbeddings:
    """Placeholder that defers to db._get_embeddings() on first use."""

    def embed_query(self, text: str) -> list[float]:
        from services.memory.db import _get_embeddings
        return _get_embeddings().embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        from services.memory.db import _get_embeddings
        return _get_embeddings().embed_documents(texts)


def _lazy_embeddings():
    return _LazyEmbeddings()


def get_vectorstore(embeddings) -> VectorStore:
    return ScoredDocDBVectorSearch(
        collection=_get_collection(),
        embedding=embeddings,
        index_name=INDEX_NAME,
    )


def _doc_to_row(doc: dict) -> dict:
    doc.pop("_id", None)
    doc.pop(EMBEDDING_KEY, None)
    text = doc.pop(TEXT_KEY, "")
    id = doc.get("id", "")
    return {"id": id, "text": text, "metadata": dict(doc)}


def load_all() -> list[dict]:
    collection = _get_collection()
    if collection.count_documents({}) == 0:
        return []
    return [_doc_to_row(doc) for doc in collection.find({}).limit(10000)]


def list_rows(repo: str | None = None, limit: int = 20) -> list[dict]:
    query: dict[str, Any] = {"repo": repo} if repo else {}
    return [_doc_to_row(doc) for doc in _get_collection().find(query).limit(limit)]


def get_row(id: str) -> dict | None:
    validate_memory_id(id)
    doc = _get_collection().find_one({"id": id})
    return _doc_to_row(doc) if doc else None


def delete_row(id: str) -> None:
    validate_memory_id(id)
    result = _get_collection().delete_one({"id": id})
    if result.deleted_count == 0:
        raise KeyError(f"Memory not found: {id}")
