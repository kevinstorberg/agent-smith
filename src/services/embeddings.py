import asyncio

from src.services.base import register_service


@register_service("embeddings")
class EmbeddingsService:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None

    @classmethod
    def from_settings(cls, settings):
        from config.loader import load_default_config

        config = load_default_config()
        return cls(model_name=config.memory.embedding_model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings without blocking the event loop."""
        model = self._get_model()
        result = await asyncio.to_thread(model.encode, texts)
        return result.tolist()

    async def health_check(self) -> bool:
        """Verify the embedding model can load and produce output."""
        try:
            model = self._get_model()
            test_output = await asyncio.to_thread(model.encode, ["health check"])
            return test_output is not None and len(test_output) > 0
        except Exception:
            return False

    async def close(self) -> None:
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model
