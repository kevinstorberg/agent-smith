from src.settings import get_settings


def _ttl_to_milliseconds(ttl: float | None) -> int | None:
    if ttl is None:
        return None
    if ttl <= 0:
        raise ValueError(f"ttl must be positive, got {ttl}")
    return max(1, int(ttl * 1000))


class RedisCacheBackend:
    def __init__(self, *, url: str | None = None, client=None) -> None:
        self._client = client or self._create_client(url or get_settings().REDIS_URL)

    def _create_client(self, url: str):
        try:
            from redis import asyncio as redis
        except ImportError as e:
            raise RuntimeError("RedisCacheBackend requires `poetry install --with redis`") from e
        return redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def set(self, key: str, value: str, ttl: float | None = None) -> None:
        px = _ttl_to_milliseconds(ttl)
        if px is None:
            await self._client.set(key, value)
        else:
            await self._client.set(key, value, px=px)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def exists(self, key: str) -> bool:
        return bool(await self._client.exists(key))

    async def close(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close is not None:
            await close()
