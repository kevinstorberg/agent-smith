import asyncio

from memory.base import MemoryBackend
from src.settings import get_settings


def _result_get(value, key: str, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


class PineconeBackend(MemoryBackend):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        index_name: str | None = None,
        namespace: str | None = None,
        index=None,
    ):
        settings = get_settings()
        self._namespace = namespace if namespace is not None else settings.PINECONE_NAMESPACE
        self._index = index or self._create_index(
            api_key=api_key or settings.PINECONE_API_KEY,
            index_name=index_name or settings.PINECONE_INDEX_NAME,
        )

    def _create_index(self, *, api_key: str, index_name: str):
        if not api_key:
            raise ValueError("PINECONE_API_KEY is required when using PineconeBackend")
        if not index_name:
            raise ValueError("PINECONE_INDEX_NAME is required when using PineconeBackend")
        try:
            from pinecone import Pinecone
        except ImportError as e:
            raise RuntimeError("PineconeBackend requires `poetry install --with pinecone`") from e

        client = Pinecone(api_key=api_key)
        if hasattr(client, "Index"):
            return client.Index(index_name)
        return client.index(index_name)

    def _namespace_kwargs(self) -> dict:
        if self._namespace:
            return {"namespace": self._namespace}
        return {}

    async def store(self, id: str, text: str, metadata: dict, embedding: list[float]) -> None:
        payload = {**metadata, "text": text}
        await asyncio.to_thread(
            self._index.upsert,
            vectors=[{"id": id, "values": embedding, "metadata": payload}],
            **self._namespace_kwargs(),
        )

    async def search(self, query_embedding: list[float], limit: int = 10, filters: dict | None = None) -> list[dict]:
        kwargs = {
            "vector": query_embedding,
            "top_k": limit,
            "include_metadata": True,
            **self._namespace_kwargs(),
        }
        if filters:
            kwargs["filter"] = filters

        response = await asyncio.to_thread(self._index.query, **kwargs)
        matches = _result_get(response, "matches", []) or []
        results = []
        for match in matches:
            metadata = dict(_result_get(match, "metadata", {}) or {})
            text = metadata.pop("text", "")
            results.append(
                {
                    "id": _result_get(match, "id"),
                    "text": text,
                    "metadata": metadata,
                    "score": float(_result_get(match, "score", 0.0)),
                }
            )
        return results

    async def delete(self, id: str) -> None:
        await asyncio.to_thread(self._index.delete, ids=[id], **self._namespace_kwargs())
