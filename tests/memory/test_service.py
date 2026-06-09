import pytest

from memory.service import MemoryService


class FakeMemoryBackend:
    def __init__(self) -> None:
        self.stored: list[tuple[str, str, dict, list[float]]] = []
        self.search_calls: list[tuple[list[float], int, dict | None]] = []
        self.deleted: list[str] = []

    async def store(self, id: str, text: str, metadata: dict, embedding: list[float]) -> None:
        self.stored.append((id, text, metadata, embedding))

    async def search(self, query_embedding: list[float], limit: int = 10, filters: dict | None = None) -> list[dict]:
        self.search_calls.append((query_embedding, limit, filters))
        return [{"id": "memory-1"}]

    async def delete(self, id: str) -> None:
        self.deleted.append(id)


class FakeEmbeddingsService:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text))] for text in texts]


@pytest.mark.asyncio
async def test_store_delegates_explicit_embedding_to_backend():
    backend = FakeMemoryBackend()
    service = MemoryService(backend)

    await service.store("memory-1", "text", {"kind": "note"}, embedding=[0.1, 0.2])

    assert backend.stored == [("memory-1", "text", {"kind": "note"}, [0.1, 0.2])]


@pytest.mark.asyncio
async def test_store_uses_embeddings_service_when_embedding_is_missing():
    backend = FakeMemoryBackend()
    service = MemoryService(backend, embeddings_service=FakeEmbeddingsService())

    await service.store("memory-1", "abcd", {})

    assert backend.stored == [("memory-1", "abcd", {}, [4.0])]


@pytest.mark.asyncio
async def test_store_requires_embedding_or_embeddings_service():
    service = MemoryService(FakeMemoryBackend())

    with pytest.raises(ValueError, match="No embedding provided"):
        await service.store("memory-1", "text", {})


@pytest.mark.asyncio
async def test_search_and_delete_delegate_to_backend():
    backend = FakeMemoryBackend()
    service = MemoryService(backend)

    results = await service.search([0.1], limit=3, filters={"kind": "note"})
    await service.delete("memory-1")

    assert results == [{"id": "memory-1"}]
    assert backend.search_calls == [([0.1], 3, {"kind": "note"})]
    assert backend.deleted == ["memory-1"]
