import pytest

from db.base import Base, TimestampMixin, UUIDMixin


@pytest.mark.unit
class TestBaseModel:
    def test_base_exists(self):
        assert Base is not None

    def test_timestamp_mixin_has_fields(self):
        assert hasattr(TimestampMixin, "created_at")
        assert hasattr(TimestampMixin, "updated_at")

    def test_uuid_mixin_has_id(self):
        assert hasattr(UUIDMixin, "id")


@pytest.mark.unit
class TestConnectionModule:
    def test_get_engine_importable(self):
        from db.connection import get_engine

        assert callable(get_engine)

    def test_get_session_importable(self):
        from db.connection import get_session

        assert callable(get_session)

    @pytest.mark.asyncio
    async def test_get_session_commits_after_successful_use(self, monkeypatch):
        from db import connection

        session = FakeSession()

        monkeypatch.setattr(connection, "get_session_factory", lambda: FakeSessionFactory(session))

        generator = connection.get_session()
        yielded = await anext(generator)

        assert yielded is session

        with pytest.raises(StopAsyncIteration):
            await anext(generator)

        assert session.committed is True
        assert session.rolled_back is False

    @pytest.mark.asyncio
    async def test_get_session_rolls_back_when_consumer_raises(self, monkeypatch):
        from db import connection

        session = FakeSession()

        monkeypatch.setattr(connection, "get_session_factory", lambda: FakeSessionFactory(session))

        generator = connection.get_session()
        yielded = await anext(generator)

        assert yielded is session

        with pytest.raises(RuntimeError, match="consumer failed"):
            await generator.athrow(RuntimeError("consumer failed"))

        assert session.committed is False
        assert session.rolled_back is True

    @pytest.mark.asyncio
    async def test_dispose_engine_disposes_engine_and_resets_singletons(self, monkeypatch):
        from db import connection

        fake_get_engine = FakeGetEngine()
        fake_get_session_factory = FakeResettable()

        monkeypatch.setattr(connection, "get_engine", fake_get_engine)
        monkeypatch.setattr(connection, "get_session_factory", fake_get_session_factory)

        await connection.dispose_engine()

        assert fake_get_engine.engine.disposed is True
        assert fake_get_engine.reset_called is True
        assert fake_get_session_factory.reset_called is True


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def __call__(self) -> FakeSession:
        return self._session


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class FakeGetEngine:
    def __init__(self) -> None:
        self.engine = FakeEngine()
        self.reset_called = False

    def __call__(self) -> FakeEngine:
        return self.engine

    def reset(self) -> None:
        self.reset_called = True


class FakeResettable:
    def __init__(self) -> None:
        self.reset_called = False

    def reset(self) -> None:
        self.reset_called = True
