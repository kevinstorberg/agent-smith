from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_module():
    """Re-import connection module with a fresh DATABASE_URL each test."""
    import importlib
    import services.db.connection as mod
    yield
    importlib.reload(mod)


def _patch_url(monkeypatch, url: str):
    monkeypatch.setattr("services.db.connection.DATABASE_URL", url)


def test_get_connection_rejects_non_postgresql_url(monkeypatch):
    _patch_url(monkeypatch, "mysql://localhost/agent_smith")
    from services.db.connection import get_connection

    with pytest.raises(ValueError, match="DATABASE_URL must be a postgresql:// URL"):
        with get_connection():
            pass


def test_get_connection_rejects_sqlite_url(monkeypatch):
    _patch_url(monkeypatch, "sqlite:///tmp/test.db")
    from services.db.connection import get_connection

    with pytest.raises(ValueError, match="DATABASE_URL must be a postgresql:// URL"):
        with get_connection():
            pass


@patch("services.db.connection.psycopg2")
def test_get_connection_accepts_postgresql_scheme(mock_pg, monkeypatch):
    _patch_url(monkeypatch, "postgresql://localhost/agent_smith")
    mock_conn = MagicMock()
    mock_pg.connect.return_value = mock_conn
    from services.db.connection import get_connection

    with get_connection() as conn:
        assert conn is mock_conn

    mock_pg.connect.assert_called_once_with("postgresql://localhost/agent_smith")
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()


@patch("services.db.connection.psycopg2")
def test_get_connection_accepts_postgres_scheme(mock_pg, monkeypatch):
    _patch_url(monkeypatch, "postgres://localhost/agent_smith")
    mock_conn = MagicMock()
    mock_pg.connect.return_value = mock_conn
    from services.db.connection import get_connection

    with get_connection() as conn:
        assert conn is mock_conn


@patch("services.db.connection.psycopg2")
def test_get_connection_rolls_back_on_exception(mock_pg, monkeypatch):
    _patch_url(monkeypatch, "postgresql://localhost/agent_smith")
    mock_conn = MagicMock()
    mock_pg.connect.return_value = mock_conn
    from services.db.connection import get_connection

    with pytest.raises(RuntimeError):
        with get_connection() as conn:
            raise RuntimeError("boom")

    mock_conn.rollback.assert_called_once()
    mock_conn.commit.assert_not_called()
    mock_conn.close.assert_called_once()
