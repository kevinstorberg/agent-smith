import json
from typing import Any

from cache.base import CacheBackend


class CacheService:
    """Cache service with namespace isolation and JSON serialization.

    Adds value beyond raw backend access:
    - Namespace prefixing prevents key collisions between subsystems
    - JSON serialization/deserialization for structured data
    """

    def __init__(self, backend: CacheBackend, namespace: str = "") -> None:
        self._backend = backend
        self._namespace = namespace

    def _prefixed(self, key: str) -> str:
        if self._namespace:
            return f"{self._namespace}:{key}"
        return key

    async def get(self, key: str) -> str | None:
        return await self._backend.get(self._prefixed(key))

    async def get_json(self, key: str) -> Any | None:
        """Get and deserialize a JSON-encoded value."""
        raw = await self._backend.get(self._prefixed(key))
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: str, ttl: float | None = None) -> None:
        await self._backend.set(self._prefixed(key), value, ttl=ttl)

    async def set_json(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Serialize and store a JSON-encodable value."""
        await self._backend.set(self._prefixed(key), json.dumps(value), ttl=ttl)

    async def delete(self, key: str) -> None:
        await self._backend.delete(self._prefixed(key))

    async def exists(self, key: str) -> bool:
        return await self._backend.exists(self._prefixed(key))
