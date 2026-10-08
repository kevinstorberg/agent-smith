from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scripts.shared.database_safety import database_identity, validate_database_target
from scripts.shared.env import environment


@pytest.mark.parametrize("url", [
    "postgresql://postgres@remote/agent_smith_test",
    "postgresql://postgres@localhost/production",
    "postgresql://postgres@localhost/agent_smith_test?host=remote",
    "postgresql://postgres@localhost/agent_smith_test?hostaddr=10.0.0.1",
    "postgresql://postgres@localhost/agent_smith_test?service=production",
    "postgresql://postgres@localhost/agent_smith_test?dbname=production",
    "postgresql:///agent_smith_test",
])
def test_unsafe_test_targets_are_rejected(url):
    with pytest.raises(ValueError):
        validate_database_target("test", url)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_test_targets_accept_loopback(host):
    validate_database_target("test", f"postgresql://postgres@{host}:5433/agent_smith_test")


@pytest.mark.parametrize("app_env", ["development", "test"])
def test_production_alias_is_rejected_ignoring_credentials_and_localhost_alias(app_env):
    with pytest.raises(ValueError, match="matches production"):
        validate_database_target(app_env, "postgresql://tester@127.0.0.1/app_test",
                                 "postgresql://owner:secret@localhost:5432/app_test")


def test_invalid_environment_is_rejected():
    with pytest.raises(ValueError, match="APP_ENV"):
        validate_database_target("prod", "postgresql://localhost/production")


def test_production_cannot_select_test_database():
    with pytest.raises(ValueError, match="test database"):
        validate_database_target("production", "postgresql://localhost/agent_smith_test")


def test_environment_selects_only_requested_overrides_and_preserves_process_values(tmp_path):
    (tmp_path / ".env.default").write_text("SHARED=default\nDASHBOARD_PORT=7654\n")
    (tmp_path / ".env.development").write_text("SHARED=dev\nDEV_ONLY=yes\n")
    (tmp_path / ".env.production").write_text("SHARED=prod\nPRODUCTION_ONLY=secret\n")
    result = environment(tmp_path, "development", {"SHARED": "process"})
    assert result["SHARED"] == "process"
    assert result["DEV_ONLY"] == "yes"
    assert "PRODUCTION_ONLY" not in result
    assert result["DASHBOARD_PORT"] == "7655"
    assert result["MEMORY_STORE_PATH"] == str(tmp_path / "memory_store/development")


def test_production_database_creation_fails_before_connect(monkeypatch):
    from services.db.create import create_database
    connect = MagicMock()
    monkeypatch.setattr("psycopg2.connect", connect)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValueError, match="creation is disabled"):
        create_database("postgresql://localhost/production")
    connect.assert_not_called()


def test_test_database_creation_fails_before_connect_for_remote_target(monkeypatch):
    from services.db.create import create_database
    connect = MagicMock()
    monkeypatch.setattr("psycopg2.connect", connect)
    with pytest.raises(ValueError, match="loopback"):
        create_database("postgresql://remote/agent_smith_test")
    connect.assert_not_called()


def test_production_startup_checks_schema_without_migrating(monkeypatch):
    import services.db as db
    check = MagicMock()
    upgrade = MagicMock()
    monkeypatch.setattr(db, "APP_ENV", "production")
    monkeypatch.setattr(db, "check_production_schema", check)
    monkeypatch.setattr("alembic.command.upgrade", upgrade)
    db.init_db()
    check.assert_called_once()
    upgrade.assert_not_called()


@pytest.mark.parametrize("actual", [{"head"}, {"old"}])
def test_production_schema_check_is_read_only_and_rejects_drift(monkeypatch, actual):
    import services.db as db
    from alembic.config import Config
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    create_engine = MagicMock(return_value=engine)
    monkeypatch.setattr("sqlalchemy.create_engine", create_engine)
    script = MagicMock()
    script.get_heads.return_value = ["head"]
    monkeypatch.setattr("alembic.script.ScriptDirectory.from_config", lambda _: script)
    migration = MagicMock()
    migration.get_current_heads.return_value = actual
    monkeypatch.setattr("alembic.runtime.migration.MigrationContext.configure", lambda _: migration)
    if actual == {"head"}:
        db.check_production_schema(Config())
    else:
        with pytest.raises(RuntimeError, match="differs from this checkout"):
            db.check_production_schema(Config())
    connection.exec_driver_sql.assert_called_once_with("SET TRANSACTION READ ONLY")
    assert create_engine.call_args.args[0].drivername == "postgresql+psycopg2"
    engine.dispose.assert_called_once()


def test_database_identity_does_not_depend_on_password():
    assert database_identity("postgres://tester:p%40ss%25word@localhost/agent_smith_test") == (
        "localhost", 5432, "agent_smith_test"
    )


def test_production_alembic_command_is_blocked_before_engine_construction(monkeypatch):
    import runpy
    from pathlib import Path
    from alembic import context
    from alembic.config import Config
    from services import config
    create_engine = MagicMock()
    monkeypatch.setattr("sqlalchemy.create_engine", create_engine)
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://localhost/production")
    monkeypatch.setattr(context, "config", Config(), raising=False)
    path = Path(__file__).resolve().parents[1] / "services/db/migrations/env.py"
    with pytest.raises(RuntimeError, match="direct Alembic commands are blocked"):
        runpy.run_path(str(path))
    create_engine.assert_not_called()


def test_production_memory_store_must_already_exist(tmp_path):
    from scripts.shared.database_safety import validate_memory_target
    with pytest.raises(ValueError, match="empty production store"):
        validate_memory_target(tmp_path, {"APP_ENV": "production", "MEMORY_STORE_PATH": str(tmp_path / "missing")})
    assert not (tmp_path / "missing").exists()


def test_nonproduction_memory_path_cannot_alias_production(tmp_path):
    from scripts.shared.database_safety import validate_memory_target
    (tmp_path / ".env.production").write_text(f"MEMORY_STORE_PATH={tmp_path / 'production'}\n")
    with pytest.raises(ValueError, match="matches production"):
        validate_memory_target(tmp_path, {"APP_ENV": "development", "MEMORY_STORE_PATH": str(tmp_path / "production")})


def test_nonproduction_pinecone_index_cannot_alias_production(tmp_path):
    from scripts.shared.database_safety import validate_memory_target
    (tmp_path / ".env.production").write_text("MEMORY_BACKEND=pinecone\nPINECONE_INDEX=live\n")
    with pytest.raises(ValueError, match="matches production"):
        validate_memory_target(tmp_path, {"APP_ENV": "test", "MEMORY_BACKEND": "pinecone", "PINECONE_INDEX": "live"})


def test_database_creation_preserves_tls_path_and_closes_connection(monkeypatch):
    from services.db.create import create_database
    connect = MagicMock()
    monkeypatch.setattr("psycopg2.connect", connect)
    connect.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
    assert create_database("postgresql://tester@localhost/agent_smith_test?sslmode=verify-full&sslrootcert=/native/cert.pem") is False
    connect.assert_called_once_with("postgresql://tester@localhost/postgres?sslmode=verify-full&sslrootcert=/native/cert.pem", connect_timeout=5)
    connect.return_value.close.assert_called_once()
