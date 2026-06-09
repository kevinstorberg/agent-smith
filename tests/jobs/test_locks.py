import pytest

from src.jobs.locks import InMemoryJobLockBackend, NoopJobLockBackend, RedisJobLockBackend, create_lock_backend


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_lock_allows_one_holder_per_key():
    backend = InMemoryJobLockBackend()

    first = await backend.acquire("job:test", ttl_seconds=60)
    second = await backend.acquire("job:test", ttl_seconds=60)
    await first.release()
    third = await backend.acquire("job:test", ttl_seconds=60)

    assert first is not None
    assert second is None
    assert third is not None
    await third.release()


def test_create_lock_backend_returns_configured_backend():
    assert isinstance(create_lock_backend("none"), NoopJobLockBackend)
    assert isinstance(create_lock_backend("memory"), InMemoryJobLockBackend)
    assert isinstance(create_lock_backend("redis", redis_url="redis://localhost:6379/0"), RedisJobLockBackend)


def test_create_lock_backend_rejects_unknown_backend():
    with pytest.raises(ValueError, match="Unknown job lock backend"):
        create_lock_backend("bogus")
