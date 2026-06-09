import pytest
from fastapi import FastAPI

from src.app import lifespan


class FakeMemoryBackend:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.unit
class TestAppLifespan:
    @pytest.mark.asyncio
    async def test_lifespan_initializes_backends_and_disposes_resources(self, monkeypatch):
        import cache.backends
        import db.connection
        import memory.backends

        app = FastAPI()
        memory_backend = FakeMemoryBackend()
        cache_backend = object()
        disposed = False

        async def fake_dispose_engine() -> None:
            nonlocal disposed
            disposed = True

        monkeypatch.setattr(memory.backends, "get_backend", lambda: memory_backend)
        monkeypatch.setattr(cache.backends, "get_cache_backend", lambda: cache_backend)
        monkeypatch.setattr(db.connection, "dispose_engine", fake_dispose_engine)

        async with lifespan(app):
            assert app.state.memory_backend is memory_backend
            assert app.state.cache_backend is cache_backend
            assert memory_backend.closed is False
            assert disposed is False

        assert memory_backend.closed is True
        assert disposed is True
