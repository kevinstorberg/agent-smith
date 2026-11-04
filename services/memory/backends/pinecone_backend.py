from __future__ import annotations

import os
import time
from collections.abc import Mapping
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from functools import partial, wraps
from multiprocessing.pool import ApplyResult
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
from services.observability import BillableEvent, error_outcome, submit_with_context
DIMENSION = MEMORY_EMBEDDING_DIMENSION
# Pinecone's maximum query top_k, and query has no pagination, so it bounds load_all.
LOAD_ALL_CEILING = 10000
ACCESS_BATCH_SECONDS = 30
REQUEST_SECONDS = 10
ACCESS_WORKERS = 4

_pc = None
_index = None
_write_lock = Lock()
_CONTROL_OPERATIONS = frozenset({"has_index", "create_index", "describe_index", "delete_index", "list_indexes", "configure_index"})
_DATA_OPERATIONS = frozenset({"query", "upsert", "fetch", "update", "delete", "describe_index_stats", "list_paginated"})


def _usage(result) -> dict[str, int]:
    usage = result.get("usage") if isinstance(result, Mapping) else getattr(result, "usage", None)
    fields = {}
    for key in ("read_units", "write_units"):
        value = usage.get(key) if isinstance(usage, Mapping) else getattr(usage, key, None)
        if type(value) is int and value >= 0:
            fields[key] = value
    return fields


def _observed_result(event, call, terminal_error=None):
    try:
        result = call()
    except BaseException as error:
        if terminal_error is None or terminal_error(error):
            event.finish(error_outcome(error), error=error)
        raise
    if isinstance(result, (ApplyResult, Future)):
        return _ObservedResult(result, event)
    event.finish(**_usage(result))
    return result


class _ObservedResult:
    def __init__(self, result, event: BillableEvent):
        self._result = result
        self._event = event

    def _terminal_error(self, error):
        # Readiness can change immediately after a waiter times out; only the stored error proves provider failure.
        if isinstance(self._result, Future):
            if not self._result.done():
                return False
            if self._result.cancelled():
                return isinstance(error, CancelledError)
            return self._result.exception(timeout=0) is error
        if not self._result.ready() or self._result.successful():
            return False
        try:
            self._result.get(timeout=0)
        except BaseException as stored_error:
            return stored_error is error
        return False

    def __getattr__(self, name):
        value = getattr(self._result, name)
        if name not in {"get", "result"} or not callable(value):
            return value

        @wraps(value)
        def complete(*args, **kwargs):
            return _observed_result(self._event, partial(value, *args, **kwargs), self._terminal_error)

        return complete


class _ObservedPinecone:
    def __init__(self, client, *, index: str | None = None):
        self._client = client
        self._index = index

    def __getattr__(self, name):
        method = getattr(self._client, name)
        operations = _DATA_OPERATIONS if self._index is not None else _CONTROL_OPERATIONS
        if name not in operations or not callable(method):
            return method

        @wraps(method)
        def call(*args, **kwargs):
            metadata = self._metadata(name, args, kwargs)
            event = BillableEvent.start("pinecone", name, **metadata)
            return _observed_result(event, partial(method, *args, **kwargs))

        return call

    def _metadata(self, name, args, kwargs):
        if self._index is None:
            index = kwargs.get("name", args[0] if args else None)
            return {"index": index} if isinstance(index, str) else {}
        namespace_position = {"fetch": 1, "upsert": 1, "delete": 2, "update": 3, "list_paginated": 3}.get(name)
        namespace = kwargs.get("namespace")
        if namespace is None and namespace_position is not None and len(args) > namespace_position:
            namespace = args[namespace_position]
        metadata = {"index": self._index, "namespace": namespace if isinstance(namespace, str) else "", "sdk_retries": 0}
        if name in {"fetch", "delete", "upsert"}:
            values = kwargs.get("vectors" if name == "upsert" else "ids", args[0] if args else None)
            if isinstance(values, (list, tuple)):
                metadata["count"] = len(values)
        elif name == "update":
            metadata["count"] = 1
        elif name == "query" and type(kwargs.get("top_k")) is int and kwargs["top_k"] >= 0:
            metadata["count"] = kwargs["top_k"]
        return metadata


def _get_pc():
    global _pc
    if _pc is None:
        api_key = os.environ.get("PINECONE_API_KEY")
        assert api_key, "PINECONE_API_KEY must be set when using pinecone backend."
        _pc = _ObservedPinecone(Pinecone(api_key=api_key))
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
        _index = _ObservedPinecone(Index(api_key=os.environ.get("PINECONE_API_KEY"), host=host, openapi_config=configuration), index=INDEX_NAME)
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
            futures = [submit_with_context(executor, patch_access, row) for row in rows]
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
