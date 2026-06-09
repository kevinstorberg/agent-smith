from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Protocol

import lancedb
from langchain_community.vectorstores import LanceDB as LanceDBVectorStore
from langchain_core.vectorstores import VectorStore

from src.agent_smith.validation import validate_memory_id
from src.settings import Settings

DIMENSION = 384
TABLE_NAME = "memories"


class MemoryVectorBackend(Protocol):
    def init(self) -> None: ...

    def get_vectorstore(self, embeddings) -> VectorStore: ...

    def load_all(self) -> list[dict]: ...

    def get_row(self, memory_id: str) -> dict | None: ...

    def delete_row(self, memory_id: str) -> None: ...


def build_row(memory_id: str, text: str, metadata: dict) -> dict:
    return {"id": memory_id, "text": text, "metadata": dict(metadata)}


class LanceDBMemoryBackend:
    def __init__(self, store_path: str) -> None:
        self.store_path = Path(store_path)

    def init(self) -> None:
        self.store_path.mkdir(parents=True, exist_ok=True)
        self._db()

    def get_vectorstore(self, embeddings) -> VectorStore:
        return LanceDBVectorStore(
            connection=self._db(),
            embedding=embeddings,
            table_name=TABLE_NAME,
            mode="append",
        )

    def load_all(self) -> list[dict]:
        table = self._get_table()
        if table is None or table.count_rows() == 0:
            return []
        return table.search().limit(10000).to_list()

    def get_row(self, memory_id: str) -> dict | None:
        validate_memory_id(memory_id)
        table = self._get_table()
        if table is None:
            return None
        results = table.search().where(f"id = '{memory_id}'", prefilter=True).limit(1).to_list()
        return results[0] if results else None

    def delete_row(self, memory_id: str) -> None:
        validate_memory_id(memory_id)
        table = self._get_table()
        if table is None:
            raise KeyError(f"Memory not found: {memory_id}")
        if not table.search().where(f"id = '{memory_id}'", prefilter=True).limit(1).to_list():
            raise KeyError(f"Memory not found: {memory_id}")
        table.delete(f"id = '{memory_id}'")

    def _db(self) -> lancedb.DBConnection:
        self.store_path.mkdir(parents=True, exist_ok=True)
        return lancedb.connect(str(self.store_path))

    def _get_table(self):
        db = self._db()
        if TABLE_NAME not in db.table_names():
            return None
        return db.open_table(TABLE_NAME)


class PineconeMemoryBackend:
    def __init__(
        self,
        *,
        index_name: str,
        cloud: str,
        region: str,
        api_key: str | None = None,
    ) -> None:
        self.index_name = index_name
        self.cloud = cloud
        self.region = region
        self.api_key = api_key or os.environ.get("PINECONE_API_KEY", "")
        self._pc = None
        self._index = None

    def init(self) -> None:
        self._get_index()

    def get_vectorstore(self, embeddings) -> VectorStore:
        from copy import deepcopy
        from datetime import datetime
        from typing import Any

        from langchain_core.documents import Document
        from langchain_pinecone import PineconeVectorStore

        class SafePineconeVectorStore(PineconeVectorStore):
            def add_documents(self, documents: list[Document], **kwargs: Any) -> list[str]:
                sanitized = [deepcopy(document) for document in documents]
                for document in sanitized:
                    for key, value in list(document.metadata.items()):
                        if isinstance(value, datetime):
                            document.metadata[key] = value.isoformat()
                kwargs.pop("current_time", None)
                return super().add_documents(sanitized, **kwargs)

        return SafePineconeVectorStore(index=self._get_index(), embedding=embeddings)

    def load_all(self) -> list[dict]:
        results = self._get_index().query(vector=[0.0] * DIMENSION, top_k=10000, include_metadata=True)
        rows = []
        for match in results.get("matches", []):
            metadata = dict(match.get("metadata", {}))
            text = metadata.pop("text", "")
            rows.append(build_row(match["id"], text, metadata))
        return rows

    def get_row(self, memory_id: str) -> dict | None:
        validate_memory_id(memory_id)
        vectors = self._fetch_vectors(self._get_index().fetch(ids=[memory_id]))
        if memory_id not in vectors:
            return None
        vector_data = vectors[memory_id]
        metadata = dict(getattr(vector_data, "metadata", None) or vector_data.get("metadata", {}))
        text = metadata.pop("text", "")
        return build_row(memory_id, text, metadata)

    def delete_row(self, memory_id: str) -> None:
        validate_memory_id(memory_id)
        vectors = self._fetch_vectors(self._get_index().fetch(ids=[memory_id]))
        if memory_id not in vectors:
            raise KeyError(f"Memory not found: {memory_id}")
        self._get_index().delete(ids=[memory_id])

    def _get_pc(self):
        from pinecone import Pinecone

        if self._pc is None:
            if not self.api_key:
                raise RuntimeError("PINECONE_API_KEY must be set when using the pinecone memory backend.")
            self._pc = Pinecone(api_key=self.api_key)
        return self._pc

    def _get_index(self):
        from pinecone import ServerlessSpec

        if self._index is None:
            pc = self._get_pc()
            if not pc.has_index(self.index_name):
                pc.create_index(
                    name=self.index_name,
                    dimension=DIMENSION,
                    metric="cosine",
                    spec=ServerlessSpec(cloud=self.cloud, region=self.region),
                )
                while not pc.describe_index(self.index_name).status["ready"]:
                    time.sleep(1)
            self._index = pc.Index(self.index_name)
        return self._index

    @staticmethod
    def _fetch_vectors(result) -> dict:
        if hasattr(result, "vectors"):
            return result.vectors or {}
        return result.get("vectors", {})


def build_memory_backend(settings: Settings) -> MemoryVectorBackend:
    backend_name = settings.MEMORY_BACKEND.lower()
    if backend_name == "lancedb":
        return LanceDBMemoryBackend(settings.MEMORY_STORE_PATH)
    if backend_name == "pinecone":
        return PineconeMemoryBackend(
            index_name=settings.PINECONE_INDEX_NAME or settings.PINECONE_INDEX,
            cloud=settings.PINECONE_CLOUD,
            region=settings.PINECONE_REGION,
            api_key=settings.PINECONE_API_KEY,
        )
    raise ValueError("Unknown Agent Smith memory backend: " f"{settings.MEMORY_BACKEND!r}")
