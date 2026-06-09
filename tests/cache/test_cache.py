import asyncio

import pytest

from cache.backends import get_cache_backend, reset_cache_backend
from cache.backends.memory import InMemoryCacheBackend
from cache.base import CacheBackend
from cache.service import CacheService


@pytest.fixture(autouse=True)
def reset_cache_backend_singleton():
    reset_cache_backend()
    yield
    reset_cache_backend()


class TestInMemoryCacheBackend:
    @pytest.mark.asyncio
    async def test_set_and_get_roundtrip(self):
        backend = InMemoryCacheBackend()
        await backend.set("key1", "value1")
        result = await backend.get("key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self):
        backend = InMemoryCacheBackend()
        result = await backend.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_removes_entry(self):
        backend = InMemoryCacheBackend()
        await backend.set("key1", "value1")
        await backend.delete("key1")
        result = await backend.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expires(self):
        backend = InMemoryCacheBackend()
        await backend.set("key1", "value1", ttl=0.1)
        await asyncio.sleep(0.15)
        result = await backend.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_exists(self):
        backend = InMemoryCacheBackend()
        assert await backend.exists("key1") is False
        await backend.set("key1", "value1")
        assert await backend.exists("key1") is True

    def test_implements_protocol(self):
        backend = InMemoryCacheBackend()
        assert isinstance(backend, CacheBackend)


class TestCacheService:
    @pytest.mark.asyncio
    async def test_service_delegates_to_backend(self):
        backend = InMemoryCacheBackend()
        service = CacheService(backend=backend)
        await service.set("k", "v")
        assert await service.get("k") == "v"


@pytest.mark.unit
class TestCacheBackendFactory:
    def test_returns_same_instance_across_calls(self):
        assert get_cache_backend() is get_cache_backend()

    def test_reset_creates_fresh_instance(self):
        backend = get_cache_backend()
        reset_cache_backend()
        assert get_cache_backend() is not backend

    @pytest.mark.asyncio
    async def test_cache_services_share_factory_backend_state(self):
        service_a = CacheService(backend=get_cache_backend())
        service_b = CacheService(backend=get_cache_backend())

        await service_a.set("shared", "value")

        assert await service_b.get("shared") == "value"
