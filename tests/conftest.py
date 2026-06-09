"""Pytest fixtures for template users.

NOTE: These fixtures are intentionally unused by the template's own tests.
The template tests demonstrate patterns by creating their own local fixtures.
When you clone this template and build your application, USE THESE FIXTURES
instead of duplicating test setup code.

Example usage in your tests:
    def test_my_feature(client):
        response = await client.get("/my-endpoint")
        assert response.status_code == 200
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import create_async_engine

from db.connection import get_session
from src.app import create_app
from src.settings import get_settings


def get_test_database_url() -> str:
    """Resolve the template's test database URL through runtime settings."""
    return get_settings().database_url_for("test")


@pytest.fixture
def app():
    """Create FastAPI app instance.

    Template fixture: Use this when you need a basic app without database setup.
    """
    return create_app()


@pytest.fixture(scope="function")
def test_engine():
    """Create test database engine with no connection pooling.

    Template fixture: Provides a test database engine for your integration tests.
    Uses NullPool to avoid connection sharing issues in tests.
    """
    engine = create_async_engine(
        get_test_database_url(),
        echo=False,
        poolclass=NullPool,  # Critical: No pooling in tests
    )
    yield engine
    # Cleanup
    engine.sync_engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine):
    """Create test session with rollback after each test.

    Template fixture: Use this when you need direct database access in tests.
    Automatically rolls back changes after each test to keep tests isolated.
    """
    from db.connection import create_session_maker

    async_session_maker = create_session_maker(test_engine)

    async with async_session_maker() as session:
        yield session
        # Rollback any uncommitted changes
        await session.rollback()


@pytest.fixture
def app_with_test_db(test_engine):
    """Create app with overridden database dependency.

    Template fixture: Use this when testing API endpoints that need database access.
    Overrides the production database with the test database automatically.
    """
    from db.connection import create_session_maker

    app = create_app()

    async def override_get_session():
        """Override get_session to use test engine."""
        async_session_maker = create_session_maker(test_engine)
        async with async_session_maker() as session:
            yield session

    # Override the dependency
    app.dependency_overrides[get_session] = override_get_session

    return app


@pytest_asyncio.fixture
async def client(app_with_test_db):
    """Create async HTTP client for testing.

    Template fixture: The primary fixture for API integration tests.
    Provides an httpx AsyncClient configured with the test database.

    Example:
        async def test_create_user(client):
            response = await client.post("/users", json={"name": "Alice"})
            assert response.status_code == 201
    """
    async with AsyncClient(transport=ASGITransport(app=app_with_test_db), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def clean_db(test_session):
    """Clean database before and after each test.

    Template fixture: Use this to ensure database isolation between tests.
    Automatically truncates all tables registered in Base.metadata.

    Example:
        async def test_user_creation(test_session, clean_db):
            # Database is clean, test in isolation
            user = User(name="Alice")
            test_session.add(user)
            await test_session.commit()
    """
    from sqlalchemy import text

    from db.base import Base

    table_names = [t.name for t in reversed(Base.metadata.sorted_tables)]

    if table_names:
        truncate_sql = f"TRUNCATE TABLE {', '.join(table_names)} CASCADE"
        await test_session.execute(text(truncate_sql))
        await test_session.commit()

    yield

    if table_names:
        truncate_sql = f"TRUNCATE TABLE {', '.join(table_names)} CASCADE"
        await test_session.execute(text(truncate_sql))
        await test_session.commit()
