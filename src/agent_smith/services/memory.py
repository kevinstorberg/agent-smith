from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache

from langchain_classic.retrievers.time_weighted_retriever import TimeWeightedVectorStoreRetriever
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

from src.agent_smith.memory_backends import MemoryVectorBackend, build_memory_backend
from src.agent_smith.responses import empty_to_none
from src.agent_smith.validation import validate_memory_id
from src.settings import Settings, get_settings

DEFAULT_LIMIT = 20
SORT_KEYS: dict[str, tuple[str, bool]] = {
    "created_at_desc": ("created_at", True),
    "created_at_asc": ("created_at", False),
    "updated_at_desc": ("updated_at", True),
    "updated_at_asc": ("updated_at", False),
}


class AgentSmithMemoryService:
    def __init__(
        self,
        *,
        backend: MemoryVectorBackend,
        model_name: str = "all-MiniLM-L6-v2",
        decay_rate: float = 0.01,
        search_fetch_ceiling: int = 200,
    ) -> None:
        self.backend = backend
        self.model_name = model_name
        self.decay_rate = decay_rate
        self.search_fetch_ceiling = search_fetch_ceiling
        self._embeddings: HuggingFaceEmbeddings | None = None
        self._retriever: TimeWeightedVectorStoreRetriever | None = None

    def init(self) -> None:
        self.backend.init()

    def add(self, content: str, repo: str | None = None, tags: list[str] | None = None) -> str:
        if not content or not content.strip():
            raise ValueError("Memory content must not be empty.")
        memory_id = str(uuid.uuid4())
        now_string = self._now()
        document = Document(
            page_content=content,
            metadata={
                "id": memory_id,
                "repo": repo or "",
                "tags": json.dumps(tags or []),
                "created_at": now_string,
                "updated_at": now_string,
            },
        )
        self._get_retriever().add_documents([document], ids=[memory_id], current_time=datetime.now())
        return memory_id

    def search(
        self,
        *,
        query: str,
        repo: str | None = None,
        tags: list[str] | None = None,
        sort: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        if not query or not query.strip():
            raise ValueError("Search query must not be empty.")
        self._validate_sort(sort)

        retriever = self._get_retriever()
        if not retriever.memory_stream:
            return []

        retriever.k = self.search_fetch_ceiling
        rows = [self._doc_to_row(document) for document in retriever.invoke(query)]
        result = self._filter_and_sort(rows, repo=repo, tags=tags, sort=sort)
        return result[: int(limit)] if limit is not None else result

    def list_memories(
        self,
        *,
        repo: str | None = None,
        tags: list[str] | None = None,
        sort: str = "created_at_desc",
        limit: int | None = None,
    ) -> list[dict]:
        rows = [self._raw_to_row(row) for row in self.backend.load_all()]
        result = self._filter_and_sort(rows, repo=repo, tags=tags, sort=sort)
        return result[: int(limit)] if limit is not None else result

    def get(self, memory_id: str) -> dict | None:
        validate_memory_id(memory_id)
        row = self.backend.get_row(memory_id)
        return self._raw_to_row(row) if row else None

    def delete(self, memory_id: str) -> None:
        validate_memory_id(memory_id)
        self.backend.delete_row(memory_id)
        if self._retriever is not None:
            self._retriever.memory_stream = [
                document for document in self._retriever.memory_stream if document.metadata.get("id") != memory_id
            ]
            for index, document in enumerate(self._retriever.memory_stream):
                document.metadata["buffer_idx"] = index

    def update(
        self,
        *,
        memory_id: str,
        content: str | None = None,
        repo: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        validate_memory_id(memory_id)
        if all(value is None for value in (content, repo, tags)):
            raise ValueError("Provide at least one of: content, repo, tags.")
        existing = self.get(memory_id)
        if existing is None:
            raise KeyError(f"Memory not found: {memory_id}")

        new_content = content if content is not None else existing["content"]
        new_repo = repo if repo is not None else empty_to_none(existing.get("repo") or "")
        new_tags = tags if tags is not None else existing.get("tags", [])
        created_at = existing.get("created_at", self._now())
        self.delete(memory_id)

        now_string = self._now()
        document = Document(
            page_content=new_content,
            metadata={
                "id": memory_id,
                "repo": new_repo or "",
                "tags": json.dumps(new_tags),
                "created_at": created_at,
                "updated_at": now_string,
            },
        )
        self._get_retriever().add_documents([document], ids=[memory_id], current_time=datetime.now())

    def _get_embeddings(self) -> HuggingFaceEmbeddings:
        if self._embeddings is None:
            self._embeddings = HuggingFaceEmbeddings(model_name=self.model_name)
        return self._embeddings

    def _get_retriever(self) -> TimeWeightedVectorStoreRetriever:
        if self._retriever is not None:
            return self._retriever

        retriever = TimeWeightedVectorStoreRetriever(
            vectorstore=self.backend.get_vectorstore(self._get_embeddings()),
            decay_rate=self.decay_rate,
            k=10,
            search_kwargs={"k": 50},
        )
        for index, row in enumerate(self.backend.load_all()):
            metadata = row.get("metadata", {})
            document = Document(
                page_content=row.get("text", ""),
                metadata={
                    **metadata,
                    "last_accessed_at": self._parse_datetime(metadata.get("last_accessed_at")),
                    "buffer_idx": index,
                },
            )
            retriever.memory_stream.append(document)

        object.__setattr__(
            retriever,
            "get_salient_docs",
            lambda query: self._id_based_salient_docs(retriever, query),
        )
        self._retriever = retriever
        return retriever

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _parse_datetime(value) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value)
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value)
            except (TypeError, ValueError):
                pass
        return datetime.now()

    @staticmethod
    def _id_based_salient_docs(retriever: TimeWeightedVectorStoreRetriever, query: str) -> dict:
        fetched = retriever.vectorstore.similarity_search_with_relevance_scores(query, **retriever.search_kwargs)
        id_to_index = {
            document.metadata.get("id"): index
            for index, document in enumerate(retriever.memory_stream)
            if document.metadata.get("id")
        }
        return {
            index: (retriever.memory_stream[index], score)
            for document, score in fetched
            if (index := id_to_index.get(document.metadata.get("id"))) is not None
        }

    @classmethod
    def _validate_sort(cls, sort: str | None) -> None:
        if sort in (None, "", "relevance") or sort in SORT_KEYS:
            return
        expected = list(SORT_KEYS) + ["relevance"]
        raise ValueError(f"Unknown sort: {sort!r}, expected one of {expected}")

    @classmethod
    def _filter_and_sort(
        cls,
        rows: list[dict],
        *,
        repo: str | None,
        tags: list[str] | None,
        sort: str | None,
    ) -> list[dict]:
        cls._validate_sort(sort)
        result = rows
        if repo:
            result = [row for row in result if row.get("repo") == repo]
        if tags:
            wanted = set(tags)
            result = [row for row in result if wanted.issubset(set(row.get("tags") or []))]
        if sort in SORT_KEYS:
            field, reverse = SORT_KEYS[sort]
            result = sorted(result, key=lambda row: row.get(field) or "", reverse=reverse)
        return result

    @classmethod
    def _to_row(cls, *, content: str, memory_id: str, metadata: dict) -> dict:
        return {
            "id": memory_id,
            "content": content,
            "repo": metadata.get("repo") or None,
            "tags": json.loads(metadata.get("tags") or "[]"),
            "created_at": metadata.get("created_at"),
            "updated_at": metadata.get("updated_at"),
        }

    @classmethod
    def _doc_to_row(cls, document: Document) -> dict:
        return cls._to_row(
            content=document.page_content,
            memory_id=document.metadata.get("id", ""),
            metadata=document.metadata,
        )

    @classmethod
    def _raw_to_row(cls, record: dict) -> dict:
        metadata = record.get("metadata", {})
        return cls._to_row(
            content=record.get("text", ""),
            memory_id=record.get("id", metadata.get("id", "")),
            metadata=metadata,
        )


@lru_cache(maxsize=1)
def get_memory_service() -> AgentSmithMemoryService:
    settings = get_settings()
    return build_memory_service(settings)


def build_memory_service(settings: Settings) -> AgentSmithMemoryService:
    return AgentSmithMemoryService(
        backend=build_memory_backend(settings),
        model_name=os.environ.get("MEMORY_EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        decay_rate=float(os.environ.get("MEMORY_DECAY_RATE", "0.01")),
        search_fetch_ceiling=int(os.environ.get("MEMORY_SEARCH_FETCH_CEILING", "200")),
    )
