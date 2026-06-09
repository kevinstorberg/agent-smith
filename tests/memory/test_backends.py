import pytest

from memory.backends.in_memory import InMemoryVectorBackend
from memory.base import MemoryBackend


@pytest.mark.unit
class TestInMemoryVectorBackend:
    @pytest.fixture
    def backend(self):
        return InMemoryVectorBackend(dimension=4)

    async def test_store_and_search(self, backend):
        await backend.store("id1", "hello world", {"tag": "test"}, [1.0, 0.0, 0.0, 0.0])
        results = await backend.search([1.0, 0.0, 0.0, 0.0], limit=1)
        assert len(results) == 1
        assert results[0]["id"] == "id1"
        assert results[0]["text"] == "hello world"

    async def test_search_returns_closest(self, backend):
        await backend.store("id1", "first", {}, [1.0, 0.0, 0.0, 0.0])
        await backend.store("id2", "second", {}, [0.0, 1.0, 0.0, 0.0])
        results = await backend.search([0.9, 0.1, 0.0, 0.0], limit=1)
        assert results[0]["id"] == "id1"

    async def test_delete_removes_entry(self, backend):
        await backend.store("id1", "hello", {}, [1.0, 0.0, 0.0, 0.0])
        await backend.delete("id1")
        results = await backend.search([1.0, 0.0, 0.0, 0.0], limit=10)
        assert results == []

    async def test_search_empty_store(self, backend):
        results = await backend.search([1.0, 0.0, 0.0, 0.0], limit=5)
        assert results == []

    async def test_implements_protocol(self, backend):
        assert isinstance(backend, MemoryBackend)

    async def test_dimension_validation(self, backend):
        with pytest.raises(ValueError, match="dimension mismatch"):
            await backend.store("id1", "text", {}, [1.0, 0.0])

    async def test_duplicate_id_overwrites(self, backend):
        await backend.store("id1", "first", {"v": 1}, [1.0, 0.0, 0.0, 0.0])
        await backend.store("id1", "second", {"v": 2}, [0.0, 1.0, 0.0, 0.0])
        results = await backend.search([0.0, 1.0, 0.0, 0.0], limit=10)
        assert len(results) == 1
        assert results[0]["text"] == "second"
        assert results[0]["metadata"] == {"v": 2}

    async def test_filter_support(self, backend):
        await backend.store("id1", "first", {"type": "a"}, [1.0, 0.0, 0.0, 0.0])
        await backend.store("id2", "second", {"type": "b"}, [0.9, 0.1, 0.0, 0.0])
        results = await backend.search([1.0, 0.0, 0.0, 0.0], limit=10, filters={"type": "b"})
        assert len(results) == 1
        assert results[0]["id"] == "id2"

    async def test_delete_fully_removes_vector(self, backend):
        await backend.store("id1", "first", {}, [1.0, 0.0, 0.0, 0.0])
        await backend.delete("id1")
        await backend.store("id2", "second", {}, [0.0, 1.0, 0.0, 0.0])
        results = await backend.search([1.0, 0.0, 0.0, 0.0], limit=10)
        assert len(results) == 1
        assert results[0]["id"] == "id2"
