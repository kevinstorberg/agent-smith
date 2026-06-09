import pytest
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.repository import BaseRepository


class RepositoryTestItem(Base):
    __tablename__ = "repository_test_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class RepositoryTestItemRepository(BaseRepository[RepositoryTestItem]):
    model = RepositoryTestItem


@pytest.mark.unit
@pytest.mark.asyncio
async def test_repository_uses_injected_session_without_committing():
    item = RepositoryTestItem(id=1, name="item")
    session = FakeRepositorySession([item])
    repository = RepositoryTestItemRepository(session)

    assert await repository.get(1) is item
    assert await repository.list(offset=1, limit=10) == [item]
    assert repository.add(item) is item
    assert await repository.refresh(item) is item
    await repository.delete(item)

    assert session.added == [item]
    assert session.deleted == [item]
    assert session.refreshed == [item]
    assert session.committed is False
    assert session.rolled_back is False


@pytest.mark.unit
def test_repository_requires_configured_model():
    repository = BaseRepository(FakeRepositorySession([]))

    with pytest.raises(ValueError, match="Repository model is not configured"):
        _ = repository.model_type


@pytest.mark.unit
@pytest.mark.asyncio
async def test_repository_validates_pagination_boundaries():
    repository = RepositoryTestItemRepository(FakeRepositorySession([]))

    with pytest.raises(ValueError, match="offset must be non-negative"):
        await repository.list(offset=-1)

    with pytest.raises(ValueError, match="limit must be positive"):
        await repository.list(limit=0)


class FakeRepositorySession:
    def __init__(self, items):
        self.items = items
        self.added = []
        self.deleted = []
        self.refreshed = []
        self.committed = False
        self.rolled_back = False

    async def get(self, model, id):
        return next((item for item in self.items if item.id == id), None)

    async def execute(self, statement):
        self.statement = statement
        return FakeResult(self.items)

    def add(self, instance):
        self.added.append(instance)

    async def delete(self, instance):
        self.deleted.append(instance)

    async def refresh(self, instance):
        self.refreshed.append(instance)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class FakeResult:
    def __init__(self, items):
        self.items = items

    def scalars(self):
        return FakeScalars(self.items)


class FakeScalars:
    def __init__(self, items):
        self.items = items

    def all(self):
        return self.items
