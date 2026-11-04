from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from threading import Lock
from typing import Any

from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone, ServerlessSpec
from pinecone.config.openapi_configuration import Configuration
from pinecone.db_data.index import Index

from scripts.shared.validation import validate_memory_id
from services.config import (
    MEMORY_EMBEDDING_DIMENSION,
    PINECONE_CLOUD as CLOUD,
    PINECONE_INDEX as INDEX_NAME,
    PINECONE_REGION as REGION,
)
from services.memory.backends import access_datetime, build_row, canonical_metadata, memory_ids, metadata_datetime
DIMENSION = MEMORY_EMBEDDING_DIMENSION
# Pinecone's maximum query top_k, and query has no pagination, so it bounds load_all.
LOAD_ALL_CEILING = 10000
ACCESS_BATCH_SECONDS = 30
REQUEST_SECONDS = 10
ACCESS_WORKERS = 4

_pc: Pinecone | None = None
_index = None
_write_lock = Lock()


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
        description = pc.describe_index(INDEX_NAME)
        host = description["host"] if isinstance(description, dict) else description.host
        configuration = Configuration()
        # SDK retries multiply request timeouts and can outlive the access batch deadline.
        configuration.retries = 0
        _index = Index(api_key=os.environ.get("PINECONE_API_KEY"), host=host, openapi_config=configuration)
    return _index


def init() -> None:
    _get_index()


class _SafePineconeVectorStore(PineconeVectorStore):

    def add_documents(self, documents: list[Document], **kwargs: Any) -> list[str]:
        sanitized = [deepcopy(d) for d in documents]
        for doc in sanitized:
            doc.metadata = canonical_metadata(doc.metadata)
            for key, val in list(doc.metadata.items()):
                if isinstance(val, datetime):
                    doc.metadata[key] = val.isoformat()
        kwargs.pop("current_time", None)
        ids = memory_ids(kwargs.get("ids") or [doc.metadata.get("id") for doc in sanitized])
        if len(ids) != len(sanitized):
            raise ValueError("Every Pinecone memory document must have one unique UUID")
        kwargs["ids"] = ids
        deadline = time.monotonic() + ACCESS_BATCH_SECONDS
        with _serialized_writes(deadline):
            existing = {row["id"]: row for row in _fetch_rows(ids, _get_index(), deadline)}
            for id, doc in zip(ids, sanitized, strict=True):
                old_access = existing.get(id, {}).get("metadata", {}).get("last_accessed_at")
                new_access = doc.metadata.get("last_accessed_at")
                if old_access is not None:
                    latest = metadata_datetime(old_access, "last_accessed_at")
                    if new_access is not None:
                        latest = max(latest, metadata_datetime(new_access, "last_accessed_at"))
                    doc.metadata["last_accessed_at"] = latest.isoformat()
            return super().add_documents(sanitized, **kwargs)


def get_vectorstore(embeddings) -> VectorStore:
    return _SafePineconeVectorStore(index=_get_index(), embedding=embeddings)


def load_all() -> list[dict]:
    index = _get_index()
    dummy_vec = [0.0] * DIMENSION
    results = index.query(vector=dummy_vec, top_k=LOAD_ALL_CEILING, include_metadata=True)
    matches = results.get("matches", [])
    if len(matches) >= LOAD_ALL_CEILING:
        raise RuntimeError(
            f"Pinecone load_all reached the {LOAD_ALL_CEILING}-match query ceiling, so memories beyond it "
            "would be silently missing; page through index.list() and fetch() instead of one query"
        )
    rows = []
    for match in matches:
        meta = dict(match.get("metadata", {}))
        text = meta.pop("text", "")
        rows.append(build_row(match["id"], text, meta))
    return rows


def list_rows(repo: str | None = None, limit: int = 20) -> list[dict]:
    rows = load_all()
    if repo:
        rows = [r for r in rows if r.get("metadata", {}).get("repo") == repo]
    return rows[:int(limit)]


def _fetch_vectors(result) -> dict:
    if hasattr(result, "vectors"):
        return result.vectors or {}
    return result.get("vectors", {})


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Pinecone memory access batch exceeded its 30-second deadline")
    return remaining


@contextmanager
def _serialized_writes(deadline: float):
    if not _write_lock.acquire(timeout=_remaining(deadline)):
        raise TimeoutError("Pinecone memory write lock exceeded its 30-second deadline")
    try:
        yield
    finally:
        _write_lock.release()


def _fetch_rows(ids: list[str], index, deadline: float) -> list[dict]:
    rows = {}
    for offset in range(0, len(ids), 1000):
        result = index.fetch(ids=ids[offset:offset + 1000], _request_timeout=min(REQUEST_SECONDS, _remaining(deadline)))
        for id, vector in _fetch_vectors(result).items():
            metadata = vector.get("metadata", {}) if isinstance(vector, dict) else vector.metadata or {}
            metadata = dict(metadata)
            text = metadata.pop("text", "")
            rows[id] = build_row(id, text, metadata)
    return [rows[id] for id in ids if id in rows]


def get_row(id: str) -> dict | None:
    rows = get_rows([id])
    return rows[0] if rows else None


def get_rows(ids: list[str]) -> list[dict]:
    ids = memory_ids(ids)
    return _fetch_rows(ids, _get_index(), time.monotonic() + ACCESS_BATCH_SECONDS) if ids else []


def touch_accessed(ids: list[str], accessed_at: datetime) -> dict[str, str]:
    ids, stamp = memory_ids(ids), access_datetime(accessed_at)
    if not ids:
        return {}
    deadline = time.monotonic() + ACCESS_BATCH_SECONDS
    with _serialized_writes(deadline):
        index = _get_index()
        rows = _fetch_rows(ids, index, deadline)

        def patch_access(row):
            existing = row["metadata"].get("last_accessed_at")
            latest = max(stamp, metadata_datetime(existing, "last_accessed_at")) if existing is not None else stamp
            value = latest.isoformat()
            if existing != value:
                index.update(id=row["id"], set_metadata={"last_accessed_at": value},
                    _request_timeout=min(REQUEST_SECONDS, _remaining(deadline)))
            return row["id"], value

        if not rows:
            return {}
        with ThreadPoolExecutor(max_workers=min(ACCESS_WORKERS, len(rows))) as executor:
            futures = [executor.submit(patch_access, row) for row in rows]
            try:
                return dict(future.result() for future in as_completed(futures, timeout=_remaining(deadline)))
            finally:
                for future in futures:
                    future.cancel()


def delete_row(id: str) -> None:
    validate_memory_id(id)
    vectors = _fetch_vectors(_get_index().fetch(ids=[id]))
    if id not in vectors:
        raise KeyError(f"Memory not found: {id}")
    _get_index().delete(ids=[id])
