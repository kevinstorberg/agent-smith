from __future__ import annotations

import runpy
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from alembic import context
from alembic.config import Config
from sqlalchemy.engine import make_url

from services import config


@pytest.mark.parametrize("offline", [True, False])
@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://postgres@localhost/agent_smith_test",
        "postgres://postgres@localhost/agent_smith_test",
        "postgresql://test:p%40ss%25word@localhost/agent_smith_test?sslmode=require",
    ],
)
def test_migrations_use_application_driver_without_changing_connection_details(
    monkeypatch, offline, database_url
):
    monkeypatch.setattr(config, "DATABASE_URL", database_url)
    monkeypatch.setattr(context, "config", Config(), raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: offline)
    configure = MagicMock()
    monkeypatch.setattr(context, "configure", configure)
    monkeypatch.setattr(context, "begin_transaction", MagicMock())
    monkeypatch.setattr(context, "run_migrations", MagicMock())
    create_engine = MagicMock()
    monkeypatch.setattr("sqlalchemy.create_engine", create_engine)

    migration_env = Path(__file__).resolve().parents[1] / "services/db/migrations/env.py"
    runpy.run_path(str(migration_env))

    expected_url = make_url(database_url).set(drivername="postgresql+psycopg2")
    if offline:
        assert configure.call_args.kwargs["url"] == expected_url
        create_engine.assert_not_called()
    else:
        assert create_engine.call_args.args[0] == expected_url
        assert configure.call_args.kwargs["connection"] is not None
