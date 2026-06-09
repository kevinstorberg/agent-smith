import sys
from types import SimpleNamespace

import pytest

import cache.backends as cache_backends
from cache.backends import create_cache_backend
from cache.backends.memory import InMemoryCacheBackend
from cache.backends.redis import RedisCacheBackend
from config.models import CacheConfig, DefaultConfig


@pytest.fixture(autouse=True)
def reset_cache_backend_factory():
    from src.settings import reset_settings

    reset_settings()
    cache_backends.reset_cache_backend()
    yield
    cache_backends.reset_cache_backend()
    reset_settings()


def test_create_cache_backend_returns_memory_backend():
    backend = create_cache_backend(CacheConfig(backend="memory"))

    assert isinstance(backend, InMemoryCacheBackend)


def test_get_cache_backend_returns_memory_backend(monkeypatch):
    config = DefaultConfig(cache=CacheConfig(backend="memory"))
    monkeypatch.setattr(cache_backends, "load_default_config", lambda: config)

    backend = cache_backends.get_cache_backend()
    assert isinstance(backend, InMemoryCacheBackend)


def test_get_cache_backend_returns_redis_backend(monkeypatch):
    config = DefaultConfig(cache=CacheConfig(backend="redis"))
    monkeypatch.setattr(cache_backends, "load_default_config", lambda: config)
    monkeypatch.setitem(
        sys.modules,
        "redis",
        SimpleNamespace(asyncio=SimpleNamespace(from_url=lambda *args, **kwargs: FakeRedisClient())),
    )

    backend = cache_backends.get_cache_backend()

    assert isinstance(backend, RedisCacheBackend)


def test_redis_cache_backend_uses_configured_url(monkeypatch):
    captured = {}

    def fake_from_url(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeRedisClient()

    monkeypatch.setenv("REDIS_URL", "redis://cache.example:6380/2")
    monkeypatch.setitem(
        sys.modules,
        "redis",
        SimpleNamespace(asyncio=SimpleNamespace(from_url=fake_from_url)),
    )

    RedisCacheBackend()

    assert captured == {"url": "redis://cache.example:6380/2", "kwargs": {"decode_responses": True}}


def test_create_cache_backend_rejects_unknown_backend():
    with pytest.raises(ValueError, match="Unknown cache backend"):
        create_cache_backend(CacheConfig(backend="unknown"))


@pytest.mark.asyncio
async def test_redis_cache_get_set_delete_exists_roundtrip():
    client = FakeRedisClient()
    backend = RedisCacheBackend(client=client)

    await backend.set("key", "value", ttl=1.5)

    assert client.last_px == 1500
    assert await backend.get("key") == "value"
    assert await backend.exists("key") is True
    await backend.delete("key")
    assert await backend.exists("key") is False


@pytest.mark.asyncio
async def test_redis_cache_rejects_non_positive_ttl():
    backend = RedisCacheBackend(client=FakeRedisClient())

    with pytest.raises(ValueError, match="ttl must be positive"):
        await backend.set("key", "value", ttl=0)


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.last_px: int | None = None
        self.closed = False

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, px: int | None = None) -> None:
        self.values[key] = value
        self.last_px = px

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def exists(self, key: str) -> int:
        return int(key in self.values)

    async def aclose(self) -> None:
        self.closed = True
