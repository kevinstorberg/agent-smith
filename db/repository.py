from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT] | None = None

    def __init__(self, session: AsyncSession, model: type[ModelT] | None = None) -> None:
        self.session = session
        self._model = model

    @property
    def model_type(self) -> type[ModelT]:
        model = self._model or self.model
        if model is None:
            raise ValueError("Repository model is not configured")
        return model

    async def get(self, id: Any) -> ModelT | None:
        return await self.session.get(self.model_type, id)

    async def list(self, *, offset: int = 0, limit: int = 100, order_by: Any | None = None) -> list[ModelT]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if limit < 1:
            raise ValueError("limit must be positive")

        statement: Select[tuple[ModelT]] = select(self.model_type).offset(offset).limit(limit)
        if order_by is not None:
            statement = statement.order_by(order_by)

        result = await self.session.execute(statement)
        return list(result.scalars().all())

    def add(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        return instance

    async def delete(self, instance: ModelT) -> None:
        await self.session.delete(instance)

    async def refresh(self, instance: ModelT) -> ModelT:
        await self.session.refresh(instance)
        return instance
