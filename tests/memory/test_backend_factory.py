import sys
from types import SimpleNamespace

import pytest

import memory.backends as memory_backends
from config.models import DefaultConfig, MemoryConfig
from memory.backends import create_memory_backend
from memory.backends.in_memory import InMemoryVectorBackend
from memory.backends.pgvector import PGVectorBackend
from memory.backends.pinecone import PineconeBackend


@pytest.fixture(autouse=True)
def reset_memory_backend_factory():
    from src.settings import reset_settings

    reset_settings()
    memory_backends.reset_backend()
    yield
    memory_backends.reset_backend()
    reset_settings()


@pytest.mark.parametrize("backend_name", ["in_memory", "faiss"])
def test_create_memory_backend_returns_in_memory_backend(backend_name):
    backend = create_memory_backend(MemoryConfig(backend=backend_name))

    assert isinstance(backend, InMemoryVectorBackend)


def test_get_backend_returns_in_memory_backend(monkeypatch):
    config = DefaultConfig(memory=MemoryConfig(backend="in_memory"))
    monkeypatch.setattr(memory_backends, "load_default_config", lambda: config)

    backend = memory_backends.get_backend()
    assert isinstance(backend, InMemoryVectorBackend)


def test_get_backend_returns_pgvector_backend(monkeypatch):
    config = DefaultConfig(memory=MemoryConfig(backend="pgvector"))
    monkeypatch.setattr(memory_backends, "load_default_config", lambda: config)

    backend = memory_backends.get_backend()

    assert isinstance(backend, PGVectorBackend)


def test_get_backend_returns_pinecone_backend(monkeypatch):
    config = DefaultConfig(memory=MemoryConfig(backend="pinecone"))
    monkeypatch.setattr(memory_backends, "load_default_config", lambda: config)
    monkeypatch.setenv("PINECONE_API_KEY", "test-key")
    monkeypatch.setenv("PINECONE_INDEX_NAME", "test-index")
    monkeypatch.setitem(sys.modules, "pinecone", SimpleNamespace(Pinecone=FakePineconeClient))

    backend = memory_backends.get_backend()

    assert isinstance(backend, PineconeBackend)


def test_create_memory_backend_rejects_unknown_backend():
    with pytest.raises(ValueError, match="Unknown memory backend"):
        create_memory_backend(MemoryConfig(backend="unknown"))


def test_pgvector_rejects_invalid_table_name():
    with pytest.raises(ValueError, match="simple SQL identifier"):
        PGVectorBackend(table_name="bad-table")


@pytest.mark.asyncio
async def test_pgvector_rejects_dimension_mismatch_before_db_use():
    session = FakeSession()
    backend = PGVectorBackend(session_factory=FakeSessionFactory(session), table_name="memory_items", dimension=2)

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        await backend.store("id1", "hello", {}, [1.0])

    assert session.executed == []


@pytest.mark.asyncio
async def test_pgvector_store_search_delete_uses_sql():
    session = FakeSession(rows=[SimpleNamespace(id="id1", text="hello", metadata={"tag": "a"}, score=0.99)])
    backend = PGVectorBackend(session_factory=FakeSessionFactory(session), table_name="memory_items", dimension=2)

    await backend.store("id1", "hello", {"tag": "a"}, [1.0, 0.0])
    results = await backend.search([1.0, 0.0], limit=5, filters={"tag": "a"})
    await backend.delete("id1")

    executed_sql = "\n".join(statement for statement, _ in session.executed)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS memory_items" in executed_sql
    assert "INSERT INTO memory_items" in executed_sql
    assert "metadata @> CAST(:filters AS jsonb)" in executed_sql
    assert "DELETE FROM memory_items" in executed_sql
    assert results == [{"id": "id1", "text": "hello", "metadata": {"tag": "a"}, "score": 0.99}]


def test_pinecone_requires_api_key():
    with pytest.raises(ValueError, match="PINECONE_API_KEY is required"):
        PineconeBackend(index_name="index")


def test_pinecone_requires_index_name():
    with pytest.raises(ValueError, match="PINECONE_INDEX_NAME is required"):
        PineconeBackend(api_key="key")


@pytest.mark.asyncio
async def test_pinecone_store_search_delete_roundtrip():
    index = FakePineconeIndex()
    backend = PineconeBackend(index=index, namespace="ns")

    await backend.store("id1", "hello", {"tag": "a"}, [1.0, 0.0])
    results = await backend.search([1.0, 0.0], limit=3, filters={"tag": "a"})
    await backend.delete("id1")

    assert index.upserts == [([{"id": "id1", "values": [1.0, 0.0], "metadata": {"tag": "a", "text": "hello"}}], "ns")]
    assert index.queries == [([1.0, 0.0], 3, True, "ns", {"tag": "a"})]
    assert index.deletes == [(["id1"], "ns")]
    assert results == [{"id": "id1", "text": "hello", "metadata": {"tag": "a"}, "score": 0.87}]


class FakeBegin:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSession:
    def __init__(self, rows=None) -> None:
        self.executed: list[tuple[str, dict | None]] = []
        self.rows = rows or []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def begin(self):
        return FakeBegin()

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), params))
        return list(self.rows)


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def __call__(self) -> FakeSession:
        return self._session


class FakePineconeIndex:
    def __init__(self) -> None:
        self.upserts = []
        self.queries = []
        self.deletes = []

    def upsert(self, *, vectors, namespace=""):
        self.upserts.append((vectors, namespace))

    def query(self, *, vector, top_k, include_metadata, namespace="", filter=None):
        self.queries.append((vector, top_k, include_metadata, namespace, filter))
        return {
            "matches": [
                {
                    "id": "id1",
                    "score": 0.87,
                    "metadata": {"text": "hello", "tag": "a"},
                }
            ]
        }

    def delete(self, *, ids, namespace=""):
        self.deletes.append((ids, namespace))


class FakePineconeClient:
    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key

    def Index(self, index_name: str):
        assert index_name == "test-index"
        return FakePineconeIndex()
