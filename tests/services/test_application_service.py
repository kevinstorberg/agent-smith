import pytest

from src.services.application import ApplicationService


class ExampleApplicationService(ApplicationService):
    def __init__(self, uow_factory, repository_factory):
        super().__init__(uow_factory)
        self.repository_factory = repository_factory

    async def create_two_records(self, first, second):
        async with self.create_unit_of_work() as uow:
            repository = self.repository_factory(uow.session)
            repository.add(first)
            repository.add(second)
            return repository.added


@pytest.mark.unit
@pytest.mark.asyncio
async def test_application_service_coordinates_repositories_in_one_unit_of_work():
    session = FakeApplicationSession()
    service = ExampleApplicationService(FakeUnitOfWorkFactory(session), FakeRepository)

    result = await service.create_two_records("first", "second")

    assert result == ["first", "second"]
    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True


class FakeRepository:
    def __init__(self, session):
        self.session = session
        self.added = []

    def add(self, value):
        self.added.append(value)
        self.session.added.append(value)
        return list(self.session.added)


class FakeApplicationSession:
    def __init__(self) -> None:
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def close(self) -> None:
        self.closed = True


class FakeUnitOfWorkFactory:
    def __init__(self, session):
        self.session = session

    def create(self):
        from db.unit_of_work import UnitOfWork

        return UnitOfWork(self.session)
