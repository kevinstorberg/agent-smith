from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.connection import get_session_factory


class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._closed = False

    @property
    def session(self) -> AsyncSession:
        self._ensure_open()
        return self._session

    async def commit(self) -> None:
        self._ensure_open()
        await self._session.commit()

    async def rollback(self) -> None:
        self._ensure_open()
        await self._session.rollback()

    async def close(self) -> None:
        if self._closed:
            return
        await self._session.close()
        self._closed = True

    async def __aenter__(self) -> Self:
        self._ensure_open()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        try:
            if exc_type is None:
                await self.commit()
            else:
                await self.rollback()
        finally:
            await self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("UnitOfWork is closed")


class UnitOfWorkFactory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory

    def create(self) -> UnitOfWork:
        factory = self._session_factory or get_session_factory()
        return UnitOfWork(factory())

    def __call__(self) -> UnitOfWork:
        return self.create()


async def get_unit_of_work() -> AsyncGenerator[UnitOfWork, None]:
    async with UnitOfWorkFactory().create() as uow:
        yield uow


@asynccontextmanager
async def unit_of_work(
    factory: UnitOfWorkFactory | None = None,
) -> AsyncGenerator[UnitOfWork, None]:
    async with (factory or UnitOfWorkFactory()).create() as uow:
        yield uow
