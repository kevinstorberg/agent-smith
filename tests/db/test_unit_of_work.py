import pytest

from db.unit_of_work import UnitOfWork, UnitOfWorkFactory, get_unit_of_work, unit_of_work


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unit_of_work_commits_and_closes_on_success():
    session = FakeUnitOfWorkSession()

    async with UnitOfWork(session) as uow:
        assert uow.session is session

    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_and_closes_on_exception():
    session = FakeUnitOfWorkSession()

    with pytest.raises(RuntimeError, match="failed"):
        async with UnitOfWork(session):
            raise RuntimeError("failed")

    assert session.committed is False
    assert session.rolled_back is True
    assert session.closed is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unit_of_work_rejects_reuse_after_close():
    uow = UnitOfWork(FakeUnitOfWorkSession())
    await uow.close()

    with pytest.raises(RuntimeError, match="UnitOfWork is closed"):
        _ = uow.session


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unit_of_work_factory_creates_boundaries_from_session_factory():
    session = FakeUnitOfWorkSession()
    factory = UnitOfWorkFactory(FakeSessionFactory(session))

    async with factory.create() as uow:
        assert uow.session is session

    assert session.committed is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unit_of_work_context_manager_accepts_factory():
    session = FakeUnitOfWorkSession()
    factory = UnitOfWorkFactory(FakeSessionFactory(session))

    async with unit_of_work(factory) as uow:
        assert uow.session is session

    assert session.committed is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_unit_of_work_dependency_commits_after_success(monkeypatch):
    import db.unit_of_work as uow_module

    session = FakeUnitOfWorkSession()
    monkeypatch.setattr(uow_module, "get_session_factory", lambda: FakeSessionFactory(session))

    generator = get_unit_of_work()
    yielded = await anext(generator)

    assert yielded.session is session

    with pytest.raises(StopAsyncIteration):
        await anext(generator)

    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_unit_of_work_dependency_rolls_back_when_consumer_raises(monkeypatch):
    import db.unit_of_work as uow_module

    session = FakeUnitOfWorkSession()
    monkeypatch.setattr(uow_module, "get_session_factory", lambda: FakeSessionFactory(session))

    generator = get_unit_of_work()
    yielded = await anext(generator)

    assert yielded.session is session

    with pytest.raises(RuntimeError, match="consumer failed"):
        await generator.athrow(RuntimeError("consumer failed"))

    assert session.committed is False
    assert session.rolled_back is True
    assert session.closed is True


class FakeUnitOfWorkSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def close(self) -> None:
        self.closed = True


class FakeSessionFactory:
    def __init__(self, session: FakeUnitOfWorkSession) -> None:
        self._session = session

    def __call__(self) -> FakeUnitOfWorkSession:
        return self._session
