from memory.base import MemoryBackend


class MemoryService:
    """Memory service with optional auto-embedding.

    Adds value beyond raw backend access:
    - Optional auto-embedding via an embeddings service
    - Consistent interface for store/search/delete
    """

    def __init__(self, backend: MemoryBackend, embeddings_service=None):
        self._backend = backend
        self._embeddings = embeddings_service

    async def store(self, id: str, text: str, metadata: dict, embedding: list[float] | None = None) -> None:
        """Store with explicit embedding, or auto-generate if embeddings_service is set."""
        if embedding is None and self._embeddings:
            embeddings = await self._embeddings.embed([text])
            embedding = embeddings[0]
        if embedding is None:
            raise ValueError("No embedding provided and no embeddings service configured")
        await self._backend.store(id, text, metadata, embedding)

    async def search(self, query_embedding: list[float], limit: int = 10, filters: dict | None = None) -> list[dict]:
        return await self._backend.search(query_embedding, limit=limit, filters=filters)

    async def delete(self, id: str) -> None:
        await self._backend.delete(id)
