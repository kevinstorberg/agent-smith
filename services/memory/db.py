from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Callable, Iterator
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock, RLock
from typing import TYPE_CHECKING, TypeVar

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_classic.retrievers.time_weighted_retriever import (
    TimeWeightedVectorStoreRetriever,
)
from langchain_huggingface import HuggingFaceEmbeddings

from services.memory.backends import (
    TIMESTAMP_FIELDS,
    MemoryBackend,
    canonical_metadata,
    get_backend,
    memory_ids,
    metadata_datetime,
)
from services.memory.content import MemoryTokenBudget, require_memory_text
from services.memory.embedding_budget import EmbeddingTokenCounter
from services.config import MEMORY_EMBEDDING_DEVICE, MEMORY_EMBEDDING_MODEL
from services.observability import action_operation

if TYPE_CHECKING:
    from services.memory.catalog import Page, Source

MODEL_NAME = MEMORY_EMBEDDING_MODEL
DECAY_RATE = float(os.environ.get("MEMORY_DECAY_RATE", "0.01"))
DEFAULT_LIMIT = int(os.environ.get("MEMORY_DEFAULT_LIMIT", "20"))
SEARCH_FETCH_CEILING = 50
LIST_PAGE_CEILING = 100
_T = TypeVar("_T")
_LOGGER = logging.getLogger("agent_smith.memory.embedding")

_embeddings: Embeddings | None = None
_retriever: TimeWeightedVectorStoreRetriever | None = None
_embeddings_lock = Lock()
_retriever_lock = Lock()


class MemoryConflictError(RuntimeError):
    pass


class MemoryContextUnavailable(RuntimeError):
    pass


class _SerializedEmbeddings(Embeddings):
    def __init__(self, model: Embeddings):
        self._model = model
        self._lock = RLock()
        self._counter = EmbeddingTokenCounter(model)
        self._budget_reported = False

    def memory_token_budget(self) -> MemoryTokenBudget:
        with self._lock:
            if not self._budget_reported:
                _LOGGER.info(
                    "Memory embedding budget configuration: %s",
                    self._counter.diagnostics(),
                )
                self._budget_reported = True
            return MemoryTokenBudget(
                self._counter.max_tokens,
                self._counter.special_tokens,
                self._count_memory_tokens,
            )

    def _count_memory_tokens(self, content: str) -> int:
        with self._lock:
            return self._counter.count(content)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            budget = self.memory_token_budget()
            for content in texts:
                budget.require(content)
            return self._model.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        with self._lock:
            return self._model.embed_query(text)


def _get_embeddings() -> Embeddings:
    global _embeddings
    if _embeddings is None:
        with _embeddings_lock:
            if _embeddings is None:
                offline = any(
                    os.environ.get(key, "").upper() in {"1", "ON", "YES", "TRUE"}
                    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
                )
                model_kwargs = {"device": MEMORY_EMBEDDING_DEVICE}
                if offline:
                    model_kwargs["local_files_only"] = True
                with action_operation(
                    "hugging_face",
                    "load",
                    owner="embedding",
                    local_only=offline,
                    model_role="memory_embedding",
                    reason="offline_cache" if offline else "cache_or_download",
                ):
                    model = HuggingFaceEmbeddings(
                        model_name=MODEL_NAME, model_kwargs=model_kwargs
                    )
                _embeddings = _SerializedEmbeddings(model)
    return _embeddings


def get_embeddings() -> Embeddings:
    """Share the serialized encoder without opening a memory vector store."""
    return _get_embeddings()


def get_memory_token_budget() -> MemoryTokenBudget:
    factory = getattr(_get_embeddings(), "memory_token_budget", None)
    if not callable(factory):
        raise ValueError(
            "Configured memory encoder cannot expose its native token budget"
        )
    budget = factory()
    if not isinstance(budget, MemoryTokenBudget):
        raise ValueError(
            "Configured memory encoder returned an unsupported token budget"
        )
    return budget


def prepare_memory_content(content: str, *, strict: bool = False) -> str:
    require_memory_text(content)
    budget = get_memory_token_budget()
    return budget.require(content) if strict else budget.normalize(content)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_retriever() -> TimeWeightedVectorStoreRetriever:
    return TimeWeightedVectorStoreRetriever(
        vectorstore=get_backend().get_vectorstore(_get_embeddings()),
        decay_rate=DECAY_RATE,
        k=10,
        search_kwargs={"k": SEARCH_FETCH_CEILING},
    )


def _get_retriever() -> TimeWeightedVectorStoreRetriever:
    global _retriever
    if _retriever is not None:
        return _retriever

    with _retriever_lock:
        if _retriever is not None:
            return _retriever

        backend = get_backend()
        if _pinecone_source(backend) is not None:
            raise RuntimeError(
                "Full Pinecone hydration is disabled; use paginated listing or explicit maintenance"
            )
        retriever = _new_retriever()

        rows = backend.load_all()
        for i, row in enumerate(rows):
            meta = row.get("metadata", {})
            doc = Document(
                page_content=row.get("text", ""),
                metadata={
                    **meta,
                    "id": row.get("id") or meta.get("id"),
                    **(
                        {
                            "last_accessed_at": metadata_datetime(
                                meta["last_accessed_at"], "last_accessed_at"
                            )
                        }
                        if meta.get("last_accessed_at") is not None
                        else {}
                    ),
                    "buffer_idx": i,
                },
            )
            retriever.memory_stream.append(doc)

        _retriever = retriever

    return _retriever


_SORT_KEYS: dict[str, tuple[str, bool]] = {
    "created_at_desc": ("created_at", True),
    "created_at_asc": ("created_at", False),
    "updated_at_desc": ("updated_at", True),
    "updated_at_asc": ("updated_at", False),
}


def _validate_sort(sort: str | None) -> None:
    if sort in (None, "", "relevance") or sort in _SORT_KEYS:
        return
    raise ValueError(
        f"Unknown sort: {sort!r}, expected one of {list(_SORT_KEYS) + ['relevance']}"
    )


def _filter_and_sort(
    rows: list[dict],
    *,
    repo: str | None,
    tags: list[str] | None,
    sort: str | None,
    meeting_only: bool = False,
) -> list[dict]:
    _validate_sort(sort)
    if type(meeting_only) is not bool:
        raise ValueError("meeting_only must be a boolean")
    out = rows
    if meeting_only:
        out = [row for row in out if row.get("from_meeting", False)]
    if repo:
        out = [r for r in out if r.get("repo") == repo]
    if tags:
        wanted = set(tags)
        out = [
            r
            for r in out
            if wanted.issubset(
                set(r.get("tags") or []) | set(r.get("context_tags") or [])
            )
        ]
    if sort in _SORT_KEYS:
        field, reverse = _SORT_KEYS[sort]
        out = sorted(out, key=lambda r: r.get(field) or "", reverse=reverse)
    return out


def _stored_tags(meta: dict) -> list[str]:
    tags = meta.get("tags") or []
    return json.loads(tags) if isinstance(tags, str) else list(tags)


def _meeting_origin_tag(tag: str) -> bool:
    if tag == "meeting-memory":
        return True
    if tag.startswith("meeting:"):
        try:
            uuid.UUID(tag.removeprefix("meeting:"))
            return True
        except ValueError:
            pass
    return False


def _to_row(*, content: str, id: str, meta: dict) -> dict:
    meta = canonical_metadata(meta)
    tags = _stored_tags(meta)
    source_type, source_id = meta.get("source_type"), meta.get("source_id")
    if source_type is None and "meeting-memory" in tags:
        for tag in tags:
            if not tag.startswith("meeting:"):
                continue
            try:
                source_id = str(uuid.UUID(tag.removeprefix("meeting:")))
            except (ValueError, TypeError, AttributeError):
                continue
            source_type = "meeting"
            break
    return {
        "id": id,
        "content": content,
        "repo": meta.get("repo") or None,
        "tags": [tag for tag in tags if not _meeting_origin_tag(tag)]
        if source_type == "meeting"
        else tags,
        "source_type": source_type,
        "source_id": source_id,
        "from_meeting": source_type == "meeting",
        **{field: meta.get(field) for field in TIMESTAMP_FIELDS},
    }


def _doc_to_row(doc: Document) -> dict:
    return _to_row(
        content=doc.page_content,
        id=doc.metadata.get("id") or doc.id or "",
        meta=doc.metadata,
    )


def _raw_to_row(record: dict) -> dict:
    meta = record.get("metadata", {})
    return _to_row(
        content=record.get("text", ""),
        id=record.get("id", meta.get("id", "")),
        meta=meta,
    )


def catalog_metadata(id: str, meta: dict) -> dict:
    row = _to_row(content="", id=id, meta=meta)
    row.pop("content")
    return row


def _pinecone_source(backend: MemoryBackend) -> Source | None:
    from services.memory.backends import pinecone_backend
    from services.memory.catalog import Source

    return Source(pinecone_backend.INDEX_NAME) if backend is pinecone_backend else None


def _require_source(backend: MemoryBackend, source: Source) -> None:
    from services.memory.catalog import Unavailable

    if _pinecone_source(backend) != source:
        raise Unavailable("Memory provider configuration changed during the operation")


def _mutate_backend(
    backend: MemoryBackend,
    id: str,
    *,
    kind: str,
    metadata: Callable[[], dict] | None,
    operation: Callable[[], _T],
) -> _T:
    from services.memory import catalog

    source = _pinecone_source(backend)
    if source is None:
        return operation()

    def apply() -> _T:
        _require_source(backend, source)
        if kind == "delete" and backend.get_row(id) is None:
            raise catalog.NoWritePerformed(f"Memory not found: {id}")
        result = operation()
        _require_source(backend, source)
        return result

    return catalog.write_through(
        source,
        id,
        kind=kind,
        metadata=metadata() if metadata is not None else None,
        operation=apply,
    )


def _with_context_tags(rows: list[dict]) -> list[dict]:
    from services.meetings import labels_db
    from services.meetings.db import MeetingStorageError

    sources = {}
    for row in rows:
        if not row.get("from_meeting"):
            continue
        try:
            sources[row["source_id"]] = str(uuid.UUID(row.get("source_id")))
        except (ValueError, TypeError, AttributeError):
            continue
    try:
        labels = labels_db.for_memories(list(set(sources.values()))) if sources else {}
    except MeetingStorageError:
        raise MemoryContextUnavailable(
            "Meeting context labels could not be read; retry when the database is available"
        ) from None
    return [
        {
            **row,
            "context_tags": labels.get(sources.get(row.get("source_id")), [])
            if row.get("from_meeting")
            else [],
        }
        for row in rows
    ]


def _record_access(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    accessed = get_backend().touch_accessed([row["id"] for row in rows], _utcnow())
    if _retriever is not None:
        with _retriever_lock:
            for document in _retriever.memory_stream:
                stamp = accessed.get(document.metadata.get("id"))
                if stamp is None:
                    continue
                stamp = metadata_datetime(stamp, "last_accessed_at")
                previous = document.metadata.get("last_accessed_at")
                document.metadata["last_accessed_at"] = (
                    max(stamp, metadata_datetime(previous, "last_accessed_at"))
                    if previous is not None
                    else stamp
                )
    return [
        {**row, "last_accessed_at": accessed[row["id"]]}
        for row in rows
        if row["id"] in accessed
    ]


def _page(rows: list[dict], limit: int | None, offset: int) -> tuple[list[dict], int]:
    if type(offset) is not int or offset < 0:
        raise ValueError("Memory offset must be a nonnegative integer")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("Memory limit must be a positive integer")
    return rows[offset : offset + limit] if limit is not None else rows[offset:], len(
        rows
    )


def _refresh_rows(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    current = {
        row["id"]: row["metadata"].get("last_accessed_at")
        for row in get_backend().get_rows([row["id"] for row in rows])
    }
    return [
        {**row, "last_accessed_at": current[row["id"]]}
        for row in rows
        if row["id"] in current
    ]


def _cached_index(retriever: TimeWeightedVectorStoreRetriever, id: str) -> int | None:
    return next(
        (
            index
            for index, item in enumerate(retriever.memory_stream)
            if item.metadata.get("id") == id
        ),
        None,
    )


def _persist_document(
    retriever: TimeWeightedVectorStoreRetriever | None,
    document: Document,
    *,
    id: str,
    current_time: datetime,
    replace_index: int | None = None,
) -> None:
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("Memory write time must include a timezone")
    current_time = current_time.astimezone(timezone.utc)
    memory_document = deepcopy(document)
    memory_document.metadata.setdefault("last_accessed_at", current_time)
    memory_document.metadata.setdefault("created_at", current_time)
    # Preserve the metadata schema without reserving a concurrent cache position.
    next_index = len(retriever.memory_stream) if retriever is not None else 0
    memory_document.metadata["buffer_idx"] = (
        next_index if replace_index is None else replace_index
    )

    # Persist a separate copy first. Vector-store adapters may sanitize metadata,
    # and a failed write must not corrupt or remove the live memory-stream entry.
    backend = get_backend()

    def persist() -> list[str]:
        vectorstore = (
            retriever.vectorstore
            if retriever is not None
            else backend.get_vectorstore(_get_embeddings())
        )
        return vectorstore.add_documents(
            [deepcopy(memory_document)], ids=[id], current_time=current_time
        )

    _mutate_backend(
        backend,
        id,
        kind="upsert",
        metadata=lambda: catalog_metadata(id, memory_document.metadata),
        operation=persist,
    )
    # A listing may publish its complete snapshot while the storage write runs.
    # FIXME: Same-ID mutation ordering needs a lock spanning provider writes and
    # cache reconciliation; this lock only preserves catalog publication order.
    with _retriever_lock:
        if retriever is None:
            retriever = _retriever
        if retriever is None:
            return
        current_index = _cached_index(retriever, id)
        memory_document.metadata["buffer_idx"] = (
            len(retriever.memory_stream) if current_index is None else current_index
        )
        if current_index is None:
            retriever.memory_stream.append(memory_document)
        else:
            previous = retriever.memory_stream[current_index].metadata.get(
                "last_accessed_at"
            )
            if previous is not None:
                memory_document.metadata["last_accessed_at"] = max(
                    metadata_datetime(previous, "last_accessed_at"),
                    metadata_datetime(
                        memory_document.metadata["last_accessed_at"], "last_accessed_at"
                    ),
                )
            retriever.memory_stream[current_index] = memory_document


def _memory_document(
    id: str,
    prepared_content: str,
    repo: str | None,
    tags: list[str] | None,
    created_at: str,
    updated_at: str,
    *,
    source_type: str | None = None,
    source_id: str | None = None,
) -> Document:
    metadata = {
        "id": id,
        "repo": repo or "",
        "tags": json.dumps(tags or []),
        "created_at": created_at,
        "updated_at": updated_at,
    }
    metadata.update(source_type=source_type or "general", source_id=source_id or id)
    return Document(page_content=prepared_content, metadata=metadata)


def _validate_scope(repo: str | None, tags: list[str] | None) -> None:
    if repo is not None and (not isinstance(repo, str) or (repo and not repo.strip())):
        raise ValueError("Memory repo must be a string or null")
    if tags is not None and (
        not isinstance(tags, list)
        or any(not isinstance(tag, str) or not tag.strip() for tag in tags)
    ):
        raise ValueError("Memory tags must be a list of nonblank strings")


def _lookback_cutoff(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Memory changed_after must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _publication_time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        result = None
    if result is None or result.utcoffset() is None:
        raise ValueError(
            "Memory created_at must be an ISO timestamp with a timezone"
        ) from None
    return result.astimezone(timezone.utc)


def publish(
    id: str,
    content: str,
    repo: str | None = None,
    tags: list[str] | None = None,
    *,
    created_at: str,
    source_type: str | None = None,
    source_id: str | None = None,
) -> str:
    """Publish frozen content without rewriting a conflicting memory."""
    try:
        id = str(uuid.UUID(id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Memory publication id must be a UUID") from None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Memory content must not be empty")
    _validate_scope(repo, tags)
    if source_type is not None or source_id is not None:
        if source_type != "meeting":
            raise ValueError(
                "Memory publication source_type must be meeting when provenance is supplied"
            )
        try:
            source_id = str(uuid.UUID(source_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Meeting memory source_id must be a UUID") from None
    stamp = _publication_time(created_at)
    raw = get_backend().get_row(id)
    existing = _raw_to_row(raw) if raw else None
    if existing is not None:
        try:
            same_time = _publication_time(existing.get("created_at")) == stamp
        except ValueError:
            same_time = False
        same_fields = (
            same_time
            and existing["repo"] == (repo or None)
            and _stored_tags(raw.get("metadata", {})) == (tags or [])
            and (
                source_type is None
                or (existing.get("source_type"), existing.get("source_id"))
                == (source_type, source_id)
            )
        )
        if same_fields and existing["content"] == content:
            return id
    content = prepare_memory_content(content)
    if existing is not None:
        if not same_fields or existing["content"] != content:
            raise MemoryConflictError(
                f"Memory {id} differs from its frozen publication"
            ) from None
        return id
    doc = _memory_document(
        id,
        content,
        repo,
        tags,
        stamp.isoformat(),
        stamp.isoformat(),
        source_type=source_type,
        source_id=source_id,
    )
    replace_index = _cached_index(_retriever, id) if _retriever is not None else None
    _persist_document(
        _retriever, doc, id=id, current_time=stamp, replace_index=replace_index
    )
    return id


def search_fresh(
    query: str, repo: str | None = None, tags: list[str] | None = None, limit: int = 10
) -> list[dict]:
    """Search the backend directly; scope filters apply to at most 200 candidates."""
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise ValueError("Memory query must contain 1-1000 nonblank characters")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Memory search limit must be 1-100")
    _validate_scope(repo, tags)
    vectorstore = get_backend().get_vectorstore(_get_embeddings())
    docs = vectorstore.similarity_search(query, k=min(200, max(20, limit * 5)))
    rows = _with_context_tags([_doc_to_row(doc) for doc in docs])
    return _record_access(
        _filter_and_sort(rows, repo=repo, tags=tags, sort=None)[:limit]
    )


def init() -> None:
    get_backend().init()


def add(
    content: str,
    repo: str | None = None,
    tags: list[str] | None = None,
    *,
    strict: bool = False,
) -> str:
    id = str(uuid.uuid4())
    now_dt = _utcnow()
    now_str = now_dt.isoformat()

    content = prepare_memory_content(content, strict=strict)
    doc = _memory_document(id, content, repo, tags, now_str, now_str)

    _persist_document(_retriever, doc, id=id, current_time=now_dt)
    return id


def _ranked_rows(retriever: TimeWeightedVectorStoreRetriever, query: str) -> list[dict]:
    hits = retriever.vectorstore.similarity_search_with_relevance_scores(
        query, k=SEARCH_FETCH_CEILING
    )
    scores = {}
    for document, score in hits[:SEARCH_FETCH_CEILING]:
        id = document.metadata.get("id") or document.id
        if id:
            scores[id] = score
    records = {row["id"]: row for row in get_backend().get_rows(list(scores))}
    now = _utcnow()
    ranked = []
    for id, relevance in scores.items():
        record = records.get(id)
        if record is None:
            continue
        metadata = dict(record["metadata"])
        ranking_access = metadata.get("last_accessed_at") or metadata.get("created_at")
        metadata["last_accessed_at"] = (
            metadata_datetime(ranking_access, "last_accessed_at")
            if ranking_access is not None
            else datetime(1970, 1, 1, tzinfo=timezone.utc)
        )
        document = Document(page_content=record["text"], metadata=metadata)
        # Native invoke uses local time and changes cache before storage acknowledges access.
        score = retriever._get_combined_score(document, relevance, now)
        ranked.append((_raw_to_row(record), score))
    return [
        row
        for row, _ in sorted(ranked, key=lambda item: item[1], reverse=True)[
            :SEARCH_FETCH_CEILING
        ]
    ]


def search_page(
    query: str,
    repo: str | None = None,
    tags: list[str] | None = None,
    sort: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    meeting_only: bool = False,
) -> tuple[list[dict], int]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Search query must not be empty")
    _validate_scope(repo, tags)
    _validate_sort(sort)
    _page([], limit, offset)

    retriever = _retriever
    if retriever is None:
        retriever = _new_retriever()
    rows = _with_context_tags(_ranked_rows(retriever, query))
    result = _filter_and_sort(
        rows, repo=repo, tags=tags, sort=sort, meeting_only=meeting_only
    )
    selected, total = _page(result, limit, offset)
    return _record_access(selected), total


def search(
    query: str,
    repo: str | None = None,
    tags: list[str] | None = None,
    sort: str | None = None,
    limit: int | None = None,
    meeting_only: bool = False,
) -> list[dict]:
    return search_page(
        query, repo=repo, tags=tags, sort=sort, limit=limit, meeting_only=meeting_only
    )[0]


def list_page(
    repo: str | None = None,
    tags: list[str] | None = None,
    sort: str = "created_at_desc",
    limit: int | None = None,
    offset: int = 0,
    meeting_only: bool = False,
    *,
    changed_after: datetime | None = None,
) -> tuple[list[dict], int]:
    _validate_scope(repo, tags)
    if tags is not None and len(tags) > 20:
        raise ValueError("Memory listing tags must contain at most 20 values")
    sort = "created_at_desc" if sort in (None, "") else sort
    if not isinstance(sort, str) or sort not in _SORT_KEYS:
        raise ValueError(f"Unknown sort: {sort!r}, expected one of {list(_SORT_KEYS)}")
    if type(meeting_only) is not bool:
        raise ValueError("meeting_only must be a boolean")
    _page([], limit, offset)
    if limit is not None and limit > LIST_PAGE_CEILING:
        raise ValueError(f"Memory listing limit must not exceed {LIST_PAGE_CEILING}")
    if changed_after is not None:
        changed_after = _lookback_cutoff(changed_after)

    backend = get_backend()
    source = _pinecone_source(backend)
    if source is not None:
        bounded_limit = DEFAULT_LIMIT if limit is None else limit
        _page([], bounded_limit, offset)
        if bounded_limit > LIST_PAGE_CEILING:
            raise ValueError(
                f"Memory listing limit must not exceed {LIST_PAGE_CEILING}"
            )
        rows, page = _catalog_listing_page(
            backend,
            source,
            repo=repo,
            tags=tags,
            sort=sort,
            limit=bounded_limit,
            offset=offset,
            meeting_only=meeting_only,
            changed_after=changed_after,
        )
        return rows, page.total

    retriever = _get_retriever()
    with _retriever_lock:
        rows = [_doc_to_row(doc) for doc in retriever.memory_stream]
    rows = _with_context_tags(rows)
    result = _filter_and_sort(
        rows, repo=repo, tags=tags, sort=sort, meeting_only=meeting_only
    )
    if changed_after is not None:
        result = [
            row
            for row in result
            if (stamp := row.get("updated_at") or row.get("created_at")) is not None
            and metadata_datetime(stamp, "changed_at") >= changed_after
        ]
    selected, total = _page(result, limit, offset)
    # Polling the feed observes stored access without itself counting as memory use.
    return _refresh_rows(selected), total


def _catalog_listing_page(
    backend: MemoryBackend,
    source: Source,
    *,
    repo: str | None,
    tags: list[str] | None,
    sort: str,
    limit: int,
    offset: int,
    meeting_only: bool,
    changed_after: datetime | None,
    expected_generation: int | None = None,
) -> tuple[list[dict], Page]:
    from services.memory import catalog

    page = catalog.select_page(
        source,
        repo=repo,
        tags=tags,
        sort=sort,
        limit=limit,
        offset=offset,
        meeting_only=meeting_only,
        changed_after=changed_after,
    )
    if expected_generation is not None and page.generation != expected_generation:
        raise catalog.Unavailable(
            "Memory listing changed during lookback; restart the operation"
        )
    _require_source(backend, source)
    fetched = backend.get_rows(page.ids) if page.ids else []
    _require_source(backend, source)
    catalog.check_page(source, page.generation)
    records = {}
    for record in fetched:
        id = record.get("id")
        if not isinstance(id, str) or id in records:
            raise catalog.Unavailable(
                "Memory listing records changed; repair the listing index"
            )
        records[id] = record
    if set(records) != set(page.ids):
        raise catalog.Unavailable(
            "Memory listing records changed; repair the listing index"
        )
    return [
        {**_raw_to_row(records[id]), "context_tags": page.context_tags.get(id, [])}
        for id in page.ids
    ], page


def iter_recent_memories(
    *,
    repo: str | None = None,
    changed_after: datetime,
    batch_size: int = SEARCH_FETCH_CEILING,
) -> Iterator[dict]:
    _validate_scope(repo, None)
    cutoff = _lookback_cutoff(changed_after)
    if type(batch_size) is not int or not 1 <= batch_size <= SEARCH_FETCH_CEILING:
        raise ValueError(
            f"Memory lookback batch size must be between 1 and {SEARCH_FETCH_CEILING}"
        )
    backend = get_backend()
    source = _pinecone_source(backend)
    offset, generation = 0, None
    while True:
        if source is None:
            rows, total = list_page(
                repo=repo,
                sort="created_at_desc",
                limit=batch_size,
                offset=offset,
                changed_after=cutoff,
            )
        else:
            rows, page = _catalog_listing_page(
                backend,
                source,
                repo=repo,
                tags=None,
                sort="created_at_desc",
                limit=batch_size,
                offset=offset,
                meeting_only=False,
                changed_after=cutoff,
                expected_generation=generation,
            )
            generation, total = page.generation, page.total
        yield from rows
        offset += len(rows)
        if not rows or offset >= total:
            return


def list_memories(
    repo: str | None = None,
    tags: list[str] | None = None,
    sort: str = "created_at_desc",
    limit: int | None = None,
    meeting_only: bool = False,
) -> list[dict]:
    return list_page(
        repo=repo, tags=tags, sort=sort, limit=limit, meeting_only=meeting_only
    )[0]


def get(id: str, *, record_access: bool = True) -> dict | None:
    assert id and id.strip(), "ID must not be empty."
    row = get_backend().get_row(id)
    if row is None:
        return None
    rows = _with_context_tags([_raw_to_row(row)])
    if record_access:
        rows = _record_access(rows)
    return rows[0] if rows else None


def delete(id: str) -> None:
    assert id and id.strip(), "ID must not be empty."
    id = memory_ids([id])[0]
    backend = get_backend()
    _mutate_backend(
        backend,
        id,
        kind="delete",
        metadata=None,
        operation=lambda: backend.delete_row(id),
    )

    global _retriever
    with _retriever_lock:
        if _retriever:
            _retriever.memory_stream = [
                doc for doc in _retriever.memory_stream if doc.metadata.get("id") != id
            ]
            for i, doc in enumerate(_retriever.memory_stream):
                doc.metadata["buffer_idx"] = i


def update(
    id: str,
    content: str | None = None,
    repo: str | None = None,
    tags: list[str] | None = None,
    *,
    strict: bool = False,
) -> None:
    assert id and id.strip(), "ID must not be empty."
    assert any(v is not None for v in (content, repo, tags)), (
        "Provide at least one of: content, repo, tags."
    )
    if content is not None:
        content = prepare_memory_content(content, strict=strict)
    existing = get(id, record_access=False)
    if not existing:
        raise KeyError(f"Memory not found: {id}")

    new_content = (
        content if content is not None else prepare_memory_content(existing["content"])
    )
    new_repo = repo if repo is not None else (existing.get("repo") or "")
    new_tags = tags if tags is not None else existing.get("tags", [])

    now_dt = _utcnow()
    now_str = now_dt.isoformat()

    doc = _memory_document(
        id,
        new_content,
        new_repo,
        new_tags,
        existing.get("created_at", now_str),
        now_str,
        source_type=existing.get("source_type"),
        source_id=existing.get("source_id"),
    )

    retriever = _retriever
    replace_index = _cached_index(retriever, id) if retriever is not None else None
    _persist_document(
        retriever,
        doc,
        id=id,
        current_time=now_dt,
        replace_index=replace_index,
    )
