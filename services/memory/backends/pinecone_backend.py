from __future__ import annotations

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
from pinecone.exceptions import PineconeApiException

from scripts.shared.validation import validate_memory_id
from services.config import PINECONE_INDEX as INDEX_NAME
from services.memory.backends import (
    access_datetime,
    build_row,
    canonical_metadata,
    memory_ids,
    metadata_datetime,
)
from services.observability import BillableEvent, error_outcome, submit_with_context

LIST_PAGE_SIZE = 100
ENUMERATION_SECONDS = 120
ACCESS_BATCH_SECONDS = 30
REQUEST_SECONDS = 10
ACCESS_WORKERS = 4
CURSOR_MAX_LENGTH = 8192

_index = None
_write_lock = Lock()
_CONTROL_OPERATIONS = frozenset(
    {
        "has_index",
        "create_index",
        "describe_index",
        "delete_index",
        "list_indexes",
        "configure_index",
    }
)
_DATA_OPERATIONS = frozenset(
    {
        "query",
        "upsert",
        "fetch",
        "update",
        "delete",
        "describe_index_stats",
        "list_paginated",
    }
)


def _usage(result) -> dict[str, int]:
    usage = (
        result.get("usage")
        if isinstance(result, Mapping)
        else getattr(result, "usage", None)
    )
    fields = {}
    for key in ("read_units", "write_units"):
        value = (
            usage.get(key) if isinstance(usage, Mapping) else getattr(usage, key, None)
        )
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
            return _observed_result(
                self._event, partial(value, *args, **kwargs), self._terminal_error
            )

        return complete


class _ObservedPinecone:
    def __init__(self, client, *, index: str | None = None):
        self._client = client
        self._index = index

    def __getattr__(self, name):
        method = getattr(self._client, name)
        operations = (
            _DATA_OPERATIONS if self._index is not None else _CONTROL_OPERATIONS
        )
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
            index = kwargs.get(
                "name", kwargs.get("index_name", args[0] if args else None)
            )
            return {"index": index} if isinstance(index, str) else {}
        namespace_position = {
            "fetch": 1,
            "upsert": 1,
            "delete": 2,
            "update": 3,
            "list_paginated": 3,
        }.get(name)
        namespace = kwargs.get("namespace")
        if (
            namespace is None
            and namespace_position is not None
            and len(args) > namespace_position
        ):
            namespace = args[namespace_position]
        metadata = {
            "index": self._index,
            "namespace": namespace if isinstance(namespace, str) else "",
            "sdk_retries": 0,
        }
        if name in {"fetch", "delete", "upsert"}:
            values = kwargs.get(
                "vectors" if name == "upsert" else "ids", args[0] if args else None
            )
            if isinstance(values, (list, tuple)):
                metadata["count"] = len(values)
        elif name == "update":
            metadata["count"] = 1
        elif (
            name == "query"
            and type(kwargs.get("top_k")) is int
            and kwargs["top_k"] >= 0
        ):
            metadata["count"] = kwargs["top_k"]
        elif name == "list_paginated" and type(kwargs.get("limit")) is int:
            metadata["count"] = kwargs["limit"]
        return metadata


def _get_index():
    global _index
    if _index is None:
        from services.memory.maintenance import (
            MaintenanceBudget,
            connect_existing_index,
        )
        from services.memory.catalog import Source

        _index = connect_existing_index(
            Source(INDEX_NAME),
            MaintenanceBudget(
                max_records=1, max_requests=1, deadline_seconds=REQUEST_SECONDS
            ),
        )
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
        ids = memory_ids(
            kwargs.get("ids") or [doc.metadata.get("id") for doc in sanitized]
        )
        if len(ids) != len(sanitized):
            raise ValueError("Every Pinecone memory document must have one unique UUID")
        kwargs["ids"] = ids
        deadline = time.monotonic() + ACCESS_BATCH_SECONDS
        with _serialized_writes(deadline):
            existing = {
                row["id"]: row for row in _fetch_rows(ids, _get_index(), deadline)
            }
            for id, doc in zip(ids, sanitized, strict=True):
                old_access = (
                    existing.get(id, {}).get("metadata", {}).get("last_accessed_at")
                )
                new_access = doc.metadata.get("last_accessed_at")
                if old_access is not None:
                    latest = metadata_datetime(old_access, "last_accessed_at")
                    if new_access is not None:
                        latest = max(
                            latest, metadata_datetime(new_access, "last_accessed_at")
                        )
                    doc.metadata["last_accessed_at"] = latest.isoformat()
            return super().add_documents(sanitized, **kwargs)


def get_vectorstore(embeddings) -> VectorStore:
    return _SafePineconeVectorStore(index=_get_index(), embedding=embeddings)


def load_all() -> list[dict]:
    from services.memory.maintenance import legacy_rows

    return legacy_rows(_get_index())


def list_rows(repo: str | None = None, limit: int = 20) -> list[dict]:
    if repo:
        raise ValueError(
            "Pinecone browsing does not support repository filters; use memory_search"
        )
    return browse_page(limit=limit)[0]


def browse_page(
    *, limit: int, cursor: str | None = None
) -> tuple[list[dict], str | None]:
    from services.memory.catalog import Unavailable

    if type(limit) is not int or not 1 <= limit <= LIST_PAGE_SIZE:
        raise ValueError(f"Memory page limit must be between 1 and {LIST_PAGE_SIZE}")
    if cursor is not None and (
        not isinstance(cursor, str)
        or not cursor.strip()
        or len(cursor) > CURSOR_MAX_LENGTH
    ):
        raise ValueError("Invalid memory cursor; restart browsing from the first page")
    deadline = time.monotonic() + ACCESS_BATCH_SECONDS
    try:
        index = _get_index()
        page = index.list_paginated(
            limit=limit,
            pagination_token=cursor,
            namespace="",
            _request_timeout=min(REQUEST_SECONDS, _remaining(deadline)),
        )
        _remaining(deadline)
        namespace = _response_field(page, "namespace")
        if namespace is not None and namespace not in ("", "__default__"):
            raise Unavailable("Pinecone memory page returned another namespace")
        vectors = _response_field(page, "vectors")
        if not isinstance(vectors, list) or len(vectors) > limit:
            raise Unavailable("Pinecone memory page contains invalid vector IDs")
        ids = [_response_field(vector, "id") for vector in vectors]
        if memory_ids(ids) != ids:
            raise Unavailable("Pinecone memory page IDs must be unique canonical UUIDs")
        pagination = _response_field(page, "pagination")
        if pagination is not None and not (
            isinstance(pagination, Mapping) or hasattr(pagination, "get")
        ):
            raise Unavailable("Pinecone memory page contains invalid pagination")
        next_cursor = _response_field(pagination, "next")
        if next_cursor is not None and (
            not isinstance(next_cursor, str)
            or not next_cursor.strip()
            or len(next_cursor) > CURSOR_MAX_LENGTH
            or next_cursor == cursor
        ):
            raise Unavailable("Pinecone memory page contains an invalid next cursor")
        rows = _fetch_rows(ids, index, deadline, namespace="") if ids else []
        _remaining(deadline)
        return rows, next_cursor
    except PineconeApiException as error:
        if cursor is not None and error.status == 400:
            raise ValueError(
                "Memory cursor is no longer valid; restart browsing from the first page"
            ) from error
        raise Unavailable("Pinecone memory page could not be read") from error
    except Unavailable:
        raise
    except Exception as error:
        raise Unavailable(
            "Pinecone memory page could not be read; retry the page"
        ) from error


def _response_field(result: Any, name: str, default: Any = None) -> Any:
    return (
        result.get(name, default)
        if isinstance(result, Mapping)
        else getattr(result, name, default)
    )


def _fetch_vectors(result: Any) -> dict:
    return _response_field(result, "vectors", {}) or {}


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Pinecone memory operation exceeded its deadline")
    return remaining


@contextmanager
def _serialized_writes(deadline: float):
    if not _write_lock.acquire(timeout=_remaining(deadline)):
        raise TimeoutError("Pinecone memory write lock exceeded its 30-second deadline")
    try:
        yield
    finally:
        _write_lock.release()


def _fetch_rows(
    ids: list[str], index, deadline: float, *, namespace: str | None = None
) -> list[dict]:
    rows = {}
    for offset in range(0, len(ids), 1000):
        result = index.fetch(
            ids=ids[offset : offset + 1000],
            _request_timeout=min(REQUEST_SECONDS, _remaining(deadline)),
            **({"namespace": namespace} if namespace is not None else {}),
        )
        served_namespace = _response_field(result, "namespace")
        if (
            namespace == ""
            and served_namespace is not None
            and served_namespace not in ("", "__default__")
        ):
            raise ValueError("Pinecone memory fetch returned another namespace")
        for id, vector in _fetch_vectors(result).items():
            metadata = (
                vector.get("metadata", {})
                if isinstance(vector, dict)
                else vector.metadata or {}
            )
            metadata = dict(metadata)
            text = metadata.pop("text", "")
            rows[id] = build_row(id, text, metadata)
    return [rows[id] for id in ids if id in rows]


def get_row(id: str) -> dict | None:
    rows = get_rows([id])
    return rows[0] if rows else None


def get_rows(ids: list[str]) -> list[dict]:
    ids = memory_ids(ids)
    return (
        _fetch_rows(ids, _get_index(), time.monotonic() + ACCESS_BATCH_SECONDS)
        if ids
        else []
    )


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
            latest = (
                max(stamp, metadata_datetime(existing, "last_accessed_at"))
                if existing is not None
                else stamp
            )
            value = latest.isoformat()
            if existing != value:
                index.update(
                    id=row["id"],
                    set_metadata={"last_accessed_at": value},
                    _request_timeout=min(REQUEST_SECONDS, _remaining(deadline)),
                )
            return row["id"], value

        if not rows:
            return {}
        with ThreadPoolExecutor(max_workers=min(ACCESS_WORKERS, len(rows))) as executor:
            futures = [submit_with_context(executor, patch_access, row) for row in rows]
            try:
                return dict(
                    future.result()
                    for future in as_completed(futures, timeout=_remaining(deadline))
                )
            finally:
                for future in futures:
                    future.cancel()


def delete_row(id: str) -> None:
    validate_memory_id(id)
    vectors = _fetch_vectors(_get_index().fetch(ids=[id]))
    if id not in vectors:
        raise KeyError(f"Memory not found: {id}")
    _get_index().delete(ids=[id])
