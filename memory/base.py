from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryBackend(Protocol):
    async def store(self, id: str, text: str, metadata: dict, embedding: list[float]) -> None: ...
    async def search(
        self, query_embedding: list[float], limit: int = 10, filters: dict | None = None
    ) -> list[dict]: ...
    async def delete(self, id: str) -> None: ...
