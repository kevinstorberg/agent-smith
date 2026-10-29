from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_classic.retrievers.time_weighted_retriever import (
    TimeWeightedVectorStoreRetriever,
)
from langchain_huggingface import HuggingFaceEmbeddings

from services.memory.backends import get_backend
from services.config import MEMORY_EMBEDDING_DEVICE, MEMORY_EMBEDDING_MODEL

MODEL_NAME = MEMORY_EMBEDDING_MODEL
DECAY_RATE = float(os.environ.get("MEMORY_DECAY_RATE", "0.01"))
DEFAULT_LIMIT = int(os.environ.get("MEMORY_DEFAULT_LIMIT", "20"))
SEARCH_FETCH_CEILING = int(os.environ.get("MEMORY_SEARCH_FETCH_CEILING", "200"))

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
        self._lock = Lock()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            return self._model.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        with self._lock:
            return self._model.embed_query(text)


def _get_embeddings() -> Embeddings:
    global _embeddings
    if _embeddings is None:
        with _embeddings_lock:
            if _embeddings is None:
                model = HuggingFaceEmbeddings(
                    model_name=MODEL_NAME,
                    model_kwargs={"device": MEMORY_EMBEDDING_DEVICE},
                )
                _embeddings = _SerializedEmbeddings(model)
    return _embeddings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(val) -> datetime:
    if isinstance(val, datetime):
        parsed = val
    elif isinstance(val, (int, float)):
        parsed = datetime.fromtimestamp(val, tz=timezone.utc)
    elif isinstance(val, str) and val:
        try:
            parsed = datetime.fromisoformat(val)
        except (ValueError, TypeError):
            return datetime.now()
    else:
        return datetime.now()

    # LangChain's time-weighted retriever uses naive local datetimes internally.
    # Normalize persisted timestamps to naive UTC so reloads cannot mix aware and
    # naive values during datetime subtraction.
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _id_based_salient_docs(retriever: TimeWeightedVectorStoreRetriever, query: str) -> dict:
    fetched = retriever.vectorstore.similarity_search_with_relevance_scores(
        query, **retriever.search_kwargs
    )
    id_to_idx = {
        d.metadata.get("id"): i
        for i, d in enumerate(retriever.memory_stream)
        if d.metadata.get("id")
    }
    return {
        idx: (retriever.memory_stream[idx], score)
        for doc, score in fetched
        if (idx := id_to_idx.get(doc.metadata.get("id"))) is not None
    }


def _get_retriever() -> TimeWeightedVectorStoreRetriever:
    global _retriever
    if _retriever is not None:
        return _retriever

    with _retriever_lock:
        if _retriever is not None:
            return _retriever

        backend = get_backend()
        vectorstore = backend.get_vectorstore(_get_embeddings())
        retriever = TimeWeightedVectorStoreRetriever(
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
            retriever.memory_stream.append(doc)

        object.__setattr__(
            retriever,
            "get_salient_docs",
            lambda query: _id_based_salient_docs(retriever, query),
        )
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
        out = [r for r in out if wanted.issubset(set(r.get("tags") or []) | set(r.get("context_tags") or []))]
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
        "tags": [tag for tag in tags if not _meeting_origin_tag(tag)] if source_type == "meeting" else tags,
        "source_type": source_type,
        "source_id": source_id,
        "from_meeting": source_type == "meeting",
        "created_at": meta.get("created_at"),
        "updated_at": meta.get("updated_at"),
    }


def _doc_to_row(doc: Document) -> dict:
    return _to_row(content=doc.page_content, id=doc.metadata.get("id") or doc.id or "", meta=doc.metadata)


def _raw_to_row(record: dict) -> dict:
    meta = record.get("metadata", {})
    return _to_row(content=record.get("text", ""), id=record.get("id", meta.get("id", "")), meta=meta)


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
        raise MemoryContextUnavailable("Meeting context labels could not be read; retry when the database is available") from None
    return [{**row, "context_tags": labels.get(sources.get(row.get("source_id")), []) if row.get("from_meeting") else []} for row in rows]


def _cached_index(retriever: TimeWeightedVectorStoreRetriever, id: str) -> int | None:
    return next((index for index, item in enumerate(retriever.memory_stream) if item.metadata.get("id") == id), None)


def _persist_document(
    retriever: TimeWeightedVectorStoreRetriever | None,
    document: Document,
    *,
    id: str,
    current_time: datetime,
    replace_index: int | None = None,
) -> None:
    memory_document = deepcopy(document)
    memory_document.metadata.setdefault("last_accessed_at", current_time)
    memory_document.metadata.setdefault("created_at", current_time)
    next_index = len(retriever.memory_stream) if retriever is not None else 0
    memory_document.metadata["buffer_idx"] = next_index if replace_index is None else replace_index

    # Persist a separate copy first. Vector-store adapters may sanitize metadata,
    # and a failed write must not corrupt or remove the live memory-stream entry.
    vectorstore = retriever.vectorstore if retriever is not None else get_backend().get_vectorstore(_get_embeddings())
    vectorstore.add_documents(
        [deepcopy(memory_document)], ids=[id], current_time=current_time
    )
    if retriever is None:
        return
    if replace_index is None:
        retriever.memory_stream.append(memory_document)
    else:
        retriever.memory_stream[replace_index] = memory_document


def _memory_document(id: str, content: str, repo: str | None, tags: list[str] | None, created_at: str, updated_at: str,
                     *, source_type: str | None = None, source_id: str | None = None) -> Document:
    metadata = {
        "id": id, "repo": repo or "", "tags": json.dumps(tags or []),
        "created_at": created_at, "updated_at": updated_at,
    }
    metadata.update(source_type=source_type or "general", source_id=source_id or id)
    return Document(page_content=content, metadata=metadata)


def _validate_scope(repo: str | None, tags: list[str] | None) -> None:
    if repo is not None and (not isinstance(repo, str) or (repo and not repo.strip())):
        raise ValueError("Memory repo must be a string or null")
    if tags is not None and (not isinstance(tags, list) or any(not isinstance(tag, str) or not tag.strip() for tag in tags)):
        raise ValueError("Memory tags must be a list of nonblank strings")


def _publication_time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        result = None
    if result is None or result.utcoffset() is None:
        raise ValueError("Memory created_at must be an ISO timestamp with a timezone") from None
    return result.astimezone(timezone.utc)


def publish(id: str, content: str, repo: str | None = None, tags: list[str] | None = None, *, created_at: str,
            source_type: str | None = None, source_id: str | None = None) -> str:
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
            raise ValueError("Memory publication source_type must be meeting when provenance is supplied")
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
        if (not same_time or existing["content"] != content or existing["repo"] != (repo or None)
                or _stored_tags(raw.get("metadata", {})) != (tags or [])
                or (source_type is not None and (existing.get("source_type"), existing.get("source_id")) != (source_type, source_id))):
            raise MemoryConflictError(f"Memory {id} differs from its frozen publication") from None
        return id
    doc = _memory_document(id, content, repo, tags, stamp.isoformat(), stamp.isoformat(), source_type=source_type, source_id=source_id)
    replace_index = _cached_index(_retriever, id) if _retriever is not None else None
    _persist_document(_retriever, doc, id=id, current_time=stamp.replace(tzinfo=None), replace_index=replace_index)
    return id


def search_fresh(query: str, repo: str | None = None, tags: list[str] | None = None, limit: int = 10) -> list[dict]:
    """Search the backend directly; scope filters apply to at most 200 candidates."""
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise ValueError("Memory query must contain 1-1000 nonblank characters")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Memory search limit must be 1-100")
    _validate_scope(repo, tags)
    vectorstore = get_backend().get_vectorstore(_get_embeddings())
    docs = vectorstore.similarity_search(query, k=min(200, max(20, limit * 5)))
    rows = _with_context_tags([_doc_to_row(doc) for doc in docs])
    return _filter_and_sort(rows, repo=repo, tags=tags, sort=None)[:limit]



def init() -> None:
    get_backend().init()


def add(content: str, repo: str | None = None, tags: list[str] | None = None) -> str:
    assert content and content.strip(), "Memory content must not be empty."
    id = str(uuid.uuid4())
    now_str = _now()
    now_dt = datetime.now()

    doc = _memory_document(id, content, repo, tags, now_str, now_str)

    retriever = _get_retriever()
    _persist_document(retriever, doc, id=id, current_time=now_dt)
    return id


def search(
    query: str,
    repo: str | None = None,
    tags: list[str] | None = None,
    sort: str | None = None,
    limit: int | None = None,
    meeting_only: bool = False,
) -> list[dict]:
    assert query and query.strip(), "Search query must not be empty."
    _validate_sort(sort)

    retriever = _get_retriever()
    if not retriever.memory_stream:
        return []

    retriever.k = SEARCH_FETCH_CEILING
    docs = retriever.invoke(query)
    rows = _with_context_tags([_doc_to_row(doc) for doc in docs])
    result = _filter_and_sort(rows, repo=repo, tags=tags, sort=sort, meeting_only=meeting_only)
    return result[: int(limit)] if limit is not None else result


def list_memories(
    repo: str | None = None,
    tags: list[str] | None = None,
    sort: str = "created_at_desc",
    limit: int | None = None,
    meeting_only: bool = False,
) -> list[dict]:
    # Read the retriever's stream, which add/update/delete keep current, instead of a full
    # backend load per call: on Pinecone that load is ~5 MB and exhausted the monthly egress
    # quota. Like search, it sees other processes' writes only after this process restarts.
    rows = _with_context_tags([_doc_to_row(doc) for doc in _get_retriever().memory_stream])
    result = _filter_and_sort(rows, repo=repo, tags=tags, sort=sort, meeting_only=meeting_only)
    return result[: int(limit)] if limit is not None else result


def get(id: str) -> dict | None:
    assert id and id.strip(), "ID must not be empty."
    row = get_backend().get_row(id)
    return _with_context_tags([_raw_to_row(row)])[0] if row else None


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

    now_str = _now()
    now_dt = datetime.now()

    doc = _memory_document(id, new_content, new_repo, new_tags, existing.get("created_at", now_str), now_str,
                           source_type=existing.get("source_type"), source_id=existing.get("source_id"))

    retriever = _get_retriever()
    replace_index = _cached_index(retriever, id)
    if replace_index is None:
        raise RuntimeError(
            f"Memory {id} exists in the backend but is missing from the retriever stream"
        )
    _persist_document(
        retriever,
        doc,
        id=id,
        current_time=now_dt,
        replace_index=replace_index,
    )
