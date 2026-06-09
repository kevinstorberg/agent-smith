from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from lib.cairn.singleton import singleton


@singleton
def get_engine(url: str | None = None, **kwargs) -> AsyncEngine:
    """Get or create singleton database engine."""
    if url is None:
        from src.settings import get_settings

        url = get_settings().database_url
    return create_async_engine(url, **kwargs)


def create_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create async session factory with standard configuration.

    Args:
        engine: SQLAlchemy async engine

    Returns:
        Configured async session maker
    """
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@singleton
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create singleton session factory."""
    engine = get_engine()
    return create_session_maker(engine)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose database engine and reset singletons."""
    engine = get_engine()
    if engine:
        await engine.dispose()
    # Reset both singletons
    get_engine.reset()
    get_session_factory.reset()
