import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text

from db.connection import get_engine


@dataclass
class JobLockLease:
    key: str
    _release: Callable[[], Awaitable[None]]
    acquired: bool = True

    async def release(self) -> None:
        await self._release()


class JobLockBackend(Protocol):
    async def acquire(self, key: str, *, ttl_seconds: float) -> JobLockLease | None: ...


class NoopJobLockBackend:
    async def acquire(self, key: str, *, ttl_seconds: float) -> JobLockLease | None:
        return JobLockLease(key=key, _release=_noop_release)


class InMemoryJobLockBackend:
    def __init__(self) -> None:
        self._expires_at: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, *, ttl_seconds: float) -> JobLockLease | None:
        now = time.monotonic()
        async with self._lock:
            expires_at = self._expires_at.get(key)
            if expires_at is not None and expires_at > now:
                return None
            self._expires_at[key] = now + ttl_seconds

        async def release() -> None:
            async with self._lock:
                self._expires_at.pop(key, None)

        return JobLockLease(key=key, _release=release)


class PostgresAdvisoryJobLockBackend:
    async def acquire(self, key: str, *, ttl_seconds: float) -> JobLockLease | None:
        del ttl_seconds
        connection = await get_engine().connect()
        lock_id = _lock_id(key)
        result = await connection.execute(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": lock_id})
        acquired = bool(result.scalar_one())
        if not acquired:
            await connection.close()
            return None

        async def release() -> None:
            try:
                await connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id})
            finally:
                await connection.close()

        return JobLockLease(key=key, _release=release)


class RedisJobLockBackend:
    def __init__(self, redis_url: str) -> None:
        if not redis_url:
            raise ValueError("REDIS_URL is required for Redis job locking")
        self._redis_url = redis_url

    async def acquire(self, key: str, *, ttl_seconds: float) -> JobLockLease | None:
        try:
            from redis import asyncio as redis_async
        except ImportError as e:
            raise RuntimeError("Install the redis optional dependency group to use Redis job locking") from e

        client = redis_async.from_url(self._redis_url)
        lock = client.lock(f"cairn:{key}", timeout=ttl_seconds)
        acquired = await lock.acquire(blocking=False)
        if not acquired:
            await client.aclose()
            return None

        async def release() -> None:
            try:
                await lock.release()
            finally:
                await client.aclose()

        return JobLockLease(key=key, _release=release)


def create_lock_backend(backend: str, *, redis_url: str = "") -> JobLockBackend:
    normalized = backend.lower()
    if normalized in {"none", "noop"}:
        return NoopJobLockBackend()
    if normalized == "memory":
        return InMemoryJobLockBackend()
    if normalized == "postgres":
        return PostgresAdvisoryJobLockBackend()
    if normalized == "redis":
        return RedisJobLockBackend(redis_url)
    raise ValueError(f"Unknown job lock backend: {backend!r}")


async def _noop_release() -> None:
    return None


def _lock_id(key: str) -> int:
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)
