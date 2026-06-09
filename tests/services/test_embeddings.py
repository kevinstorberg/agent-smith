import sys
from types import ModuleType, SimpleNamespace

import pytest

from src.services.embeddings import EmbeddingsService


class FakeEncoded:
    def __init__(self, values: list[list[float]]) -> None:
        self._values = values

    def __len__(self) -> int:
        return len(self._values)

    def tolist(self) -> list[list[float]]:
        return self._values


class FakeModel:
    def __init__(self, values: list[list[float]] | None = None, *, fail: bool = False) -> None:
        self.values = values or [[1.0, 2.0]]
        self.fail = fail
        self.encoded_texts: list[list[str]] = []

    def encode(self, texts: list[str]):
        self.encoded_texts.append(texts)
        if self.fail:
            raise RuntimeError("embedding failed")
        return FakeEncoded(self.values)


@pytest.mark.asyncio
async def test_embed_uses_model_and_returns_serializable_vectors(monkeypatch):
    model = FakeModel(values=[[0.1, 0.2], [0.3, 0.4]])
    service = EmbeddingsService()
    monkeypatch.setattr(service, "_get_model", lambda: model)

    result = await service.embed(["first", "second"])

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    assert model.encoded_texts == [["first", "second"]]


@pytest.mark.asyncio
async def test_health_check_returns_true_when_model_encodes(monkeypatch):
    model = FakeModel()
    service = EmbeddingsService()
    monkeypatch.setattr(service, "_get_model", lambda: model)

    assert await service.health_check() is True


@pytest.mark.asyncio
async def test_health_check_returns_false_when_model_fails(monkeypatch):
    model = FakeModel(fail=True)
    service = EmbeddingsService()
    monkeypatch.setattr(service, "_get_model", lambda: model)

    assert await service.health_check() is False


@pytest.mark.asyncio
async def test_close_clears_loaded_model():
    service = EmbeddingsService()
    service._model = object()

    await service.close()

    assert service._model is None


def test_get_model_loads_sentence_transformer_once(monkeypatch):
    module = ModuleType("sentence_transformers")
    created_models: list[str] = []

    class FakeSentenceTransformer:
        def __init__(self, model_name: str) -> None:
            created_models.append(model_name)

    module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    service = EmbeddingsService(model_name="fake-embedding-model")

    first = service._get_model()
    second = service._get_model()

    assert first is second
    assert created_models == ["fake-embedding-model"]


def test_from_settings_uses_configured_embedding_model(monkeypatch):
    import config.loader

    monkeypatch.setattr(
        config.loader,
        "load_default_config",
        lambda: SimpleNamespace(memory=SimpleNamespace(embedding_model="configured-model")),
    )

    service = EmbeddingsService.from_settings(settings=None)

    assert service._model_name == "configured-model"
