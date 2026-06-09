import pytest

from cache.backends.memory import InMemoryCacheBackend
from cache.service import CacheService


@pytest.mark.unit
class TestCacheServiceNamespace:
    @pytest.mark.asyncio
    async def test_namespace_isolates_keys(self):
        backend = InMemoryCacheBackend()
        service_a = CacheService(backend=backend, namespace="a")
        service_b = CacheService(backend=backend, namespace="b")

        await service_a.set("key", "value_a")
        await service_b.set("key", "value_b")

        assert await service_a.get("key") == "value_a"
        assert await service_b.get("key") == "value_b"

    @pytest.mark.asyncio
    async def test_empty_namespace_no_prefix(self):
        backend = InMemoryCacheBackend()
        service = CacheService(backend=backend, namespace="")
        await service.set("raw_key", "value")
        assert await backend.get("raw_key") == "value"

    @pytest.mark.asyncio
    async def test_namespace_prefix_format(self):
        backend = InMemoryCacheBackend()
        service = CacheService(backend=backend, namespace="users")
        await service.set("123", "data")
        assert await backend.get("users:123") == "data"

    @pytest.mark.asyncio
    async def test_exists_with_namespace(self):
        backend = InMemoryCacheBackend()
        service = CacheService(backend=backend, namespace="ns")
        await service.set("k", "v")
        assert await service.exists("k") is True
        assert await service.exists("other") is False

    @pytest.mark.asyncio
    async def test_delete_with_namespace(self):
        backend = InMemoryCacheBackend()
        service = CacheService(backend=backend, namespace="ns")
        await service.set("k", "v")
        await service.delete("k")
        assert await service.get("k") is None


@pytest.mark.unit
class TestCacheServiceJson:
    @pytest.mark.asyncio
    async def test_set_and_get_json_dict(self):
        backend = InMemoryCacheBackend()
        service = CacheService(backend=backend)
        data = {"name": "test", "count": 42}
        await service.set_json("obj", data)
        result = await service.get_json("obj")
        assert result == data

    @pytest.mark.asyncio
    async def test_set_and_get_json_list(self):
        backend = InMemoryCacheBackend()
        service = CacheService(backend=backend)
        data = [1, 2, 3]
        await service.set_json("arr", data)
        assert await service.get_json("arr") == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_get_json_missing_returns_none(self):
        backend = InMemoryCacheBackend()
        service = CacheService(backend=backend)
        assert await service.get_json("missing") is None

    @pytest.mark.asyncio
    async def test_json_with_ttl(self):
        backend = InMemoryCacheBackend()
        service = CacheService(backend=backend)
        await service.set_json("data", {"key": "val"}, ttl=300)
        assert await service.get_json("data") == {"key": "val"}

    @pytest.mark.asyncio
    async def test_json_with_namespace(self):
        backend = InMemoryCacheBackend()
        service = CacheService(backend=backend, namespace="api")
        await service.set_json("resp", {"status": "ok"})
        raw = await backend.get("api:resp")
        assert raw is not None
        assert "status" in raw
