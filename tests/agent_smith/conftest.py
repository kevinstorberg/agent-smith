from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from db.base import Base
from db.connection import get_engine, get_session_factory
from src.settings import reset_settings

AGENT_SMITH_TABLES = (
    "harness_configs",
    "harness_rules",
    "harness_skills",
    "harness_tools",
    "harness_hooks",
    "harness_agents",
    "plans",
    "eval_results",
    "eval_scenarios",
    "eval_suites",
    "job_executions",
    "job_configs",
    "background_jobs",
)

AGENT_SMITH_ENV_OVERRIDES = {
    "APP_ENV": "test",
    "AGENT_SMITH_AUTO_SEED": "false",
    "AGENT_SMITH_JOBS_ENABLED": "false",
    "MEMORY_BACKEND": "lancedb",
}


@pytest.fixture
def agent_smith_env():
    previous = {key: os.environ.get(key) for key in AGENT_SMITH_ENV_OVERRIDES}
    os.environ.update(AGENT_SMITH_ENV_OVERRIDES)
    reset_settings()
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_settings()


@pytest_asyncio.fixture
async def clean_agent_smith_db(agent_smith_env):
    get_session_factory.reset()
    get_engine.reset()
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _truncate_agent_smith_tables(connection)
    yield
    async with engine.begin() as connection:
        await _truncate_agent_smith_tables(connection)
    await engine.dispose()
    get_session_factory.reset()
    get_engine.reset()


async def _truncate_agent_smith_tables(connection) -> None:
    table_list = ", ".join(AGENT_SMITH_TABLES)
    await connection.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def agent_smith_client(clean_agent_smith_db):
    from src.app import create_app

    app = create_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
