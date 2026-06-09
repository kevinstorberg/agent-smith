"""In-memory vector similarity backend.

Provides a simple numpy-based vector store suitable for development and testing.
For production-scale vector search, switch to pgvector or Pinecone backends,
or use faiss-cpu directly (available as a project dependency).
"""

import numpy as np

from memory.base import MemoryBackend


class InMemoryVectorBackend(MemoryBackend):
    def __init__(self, dimension: int = 384):
        self._dimension = dimension
        self._entries: dict[str, dict] = {}
        self._vectors: dict[str, np.ndarray] = {}

    async def store(self, id: str, text: str, metadata: dict, embedding: list[float]) -> None:
        vec = np.array(embedding, dtype=np.float32)
        if vec.shape != (self._dimension,):
            raise ValueError(f"Embedding dimension mismatch: expected {self._dimension}, got {vec.shape[0]}")
        self._entries[id] = {"id": id, "text": text, "metadata": metadata}
        self._vectors[id] = vec

    async def search(self, query_embedding: list[float], limit: int = 10, filters: dict | None = None) -> list[dict]:
        if not self._vectors:
            return []

        query = np.array(query_embedding, dtype=np.float32)
        scores = []
        for id_, vec in self._vectors.items():
            entry = self._entries[id_]
            if filters:
                if not all(entry["metadata"].get(k) == v for k, v in filters.items()):
                    continue
            score = float(np.dot(query, vec) / (np.linalg.norm(query) * np.linalg.norm(vec) + 1e-10))
            scores.append((score, id_))

        scores.sort(reverse=True)
        results = []
        for score, id_ in scores[:limit]:
            entry = self._entries[id_]
            results.append({**entry, "score": score})
        return results

    async def delete(self, id: str) -> None:
        self._entries.pop(id, None)
        self._vectors.pop(id, None)
