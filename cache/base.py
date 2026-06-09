"""
Cache Backend Protocol

All cache operations are fully async. Always await them:

✅ CORRECT:
    cache = get_cache_backend()
    value = await cache.get("key")
    await cache.set("key", "value", ttl=60)
    exists = await cache.exists("key")
    await cache.delete("key")

❌ WRONG:
    value = cache.get("key")  # Returns coroutine, not value!
    cache.set("key", "value")  # Doesn't actually set!

Common mistake: Forgetting await in graph nodes or background jobs.

Example in LangGraph node:
    async def cache_check(state: State):
        cache = get_cache_backend()
        cached = await cache.get(f"result:{state['id']}")  # ✅ Must await
        if cached:
            return {"result": cached}
        return {}
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class CacheBackend(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: float | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...
