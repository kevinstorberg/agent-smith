from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from src.agent_smith.memory_backends import PineconeMemoryBackend, build_memory_backend
from src.settings import Settings


class FakeServerlessSpec:
    def __init__(self, *, cloud: str, region: str) -> None:
        self.cloud = cloud
        self.region = region


class FakePineconeClient:
    instances = []

    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key
        self.created_indexes = []
        type(self).instances.append(self)

    def has_index(self, _index_name: str) -> bool:
        return False

    def create_index(self, **kwargs) -> None:
        self.created_indexes.append(kwargs)

    def describe_index(self, _index_name: str):
        return SimpleNamespace(status={"ready": True})

    def Index(self, index_name: str):
        return FakePineconeIndex(index_name)


class FakePineconeIndex:
    def __init__(self, index_name: str = "index") -> None:
        self.index_name = index_name
        self.queries = []
        self.fetches = []
        self.deletes = []
        self.memory_id = "11111111-1111-1111-1111-111111111111"

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {"matches": [{"id": self.memory_id, "metadata": {"text": "hello", "repo": "agent-smith"}}]}

    def fetch(self, **kwargs):
        self.fetches.append(kwargs)
        return {"vectors": {self.memory_id: {"metadata": {"text": "hello", "repo": "agent-smith"}}}}

    def delete(self, **kwargs):
        self.deletes.append(kwargs)


class FakePineconeVectorStore:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def add_documents(self, documents, **kwargs):
        return [document.metadata["id"] for document in documents]


def test_pinecone_backend_refuses_missing_index_when_creation_disabled(monkeypatch):
    FakePineconeClient.instances = []
    monkeypatch.setitem(
        sys.modules,
        "pinecone",
        SimpleNamespace(Pinecone=FakePineconeClient, ServerlessSpec=FakeServerlessSpec),
    )
    backend = PineconeMemoryBackend(
        index_name="missing-index",
        cloud="aws",
        region="us-east-1",
        api_key="key",
        allow_create_index=False,
    )

    with pytest.raises(RuntimeError, match="Pinecone index 'missing-index' does not exist"):
        backend.init()

    assert FakePineconeClient.instances[0].created_indexes == []


def test_pinecone_backend_allows_missing_index_creation_when_explicit(monkeypatch):
    FakePineconeClient.instances = []
    monkeypatch.setitem(
        sys.modules,
        "pinecone",
        SimpleNamespace(Pinecone=FakePineconeClient, ServerlessSpec=FakeServerlessSpec),
    )
    backend = PineconeMemoryBackend(
        index_name="missing-index",
        cloud="aws",
        region="us-east-1",
        api_key="key",
        allow_create_index=True,
    )

    backend.init()

    assert FakePineconeClient.instances[0].created_indexes[0]["name"] == "missing-index"


def test_pinecone_backend_uses_namespace_for_all_operations(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "langchain_pinecone",
        SimpleNamespace(PineconeVectorStore=FakePineconeVectorStore),
    )
    index = FakePineconeIndex()
    backend = PineconeMemoryBackend(
        index_name="index",
        cloud="aws",
        region="us-east-1",
        api_key="key",
        namespace="prod-namespace",
        allow_create_index=False,
    )
    backend._index = index

    vectorstore = backend.get_vectorstore(embeddings=object())
    backend.load_all()
    backend.get_row(index.memory_id)
    backend.delete_row(index.memory_id)

    assert vectorstore.kwargs["namespace"] == "prod-namespace"
    assert index.queries[0]["namespace"] == "prod-namespace"
    assert index.fetches[0]["namespace"] == "prod-namespace"
    assert index.deletes[0]["namespace"] == "prod-namespace"


def test_pinecone_create_index_default_is_safe_in_production():
    settings = Settings(
        APP_ENV="production",
        MEMORY_BACKEND="pinecone",
        PINECONE_API_KEY="key",
        PINECONE_INDEX_NAME="index",
        _env_file=None,
    )

    backend = build_memory_backend(settings)

    assert isinstance(backend, PineconeMemoryBackend)
    assert backend.allow_create_index is False


def test_pinecone_create_index_default_remains_enabled_outside_production():
    settings = Settings(
        APP_ENV="development",
        MEMORY_BACKEND="pinecone",
        PINECONE_API_KEY="key",
        PINECONE_INDEX_NAME="index",
        _env_file=None,
    )

    backend = build_memory_backend(settings)

    assert isinstance(backend, PineconeMemoryBackend)
    assert backend.allow_create_index is True
