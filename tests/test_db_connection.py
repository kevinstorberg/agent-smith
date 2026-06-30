from __future__ import annotations

from unittest.mock import MagicMock

import psycopg2
import pytest
from psycopg2 import extensions
from psycopg2.pool import PoolError

import services.db.pool as pool_mod
import services.db.connection as conn_mod
from services.db.connection import get_connection


@pytest.fixture(autouse=True)
def _reset_pool():
    """Ensure each test starts and ends with no process-wide pool, so a pool
    built (or mocked) by one test never leaks into the next."""
    pool_mod.close_pool()
    yield
    pool_mod.close_pool()


def _live_conn() -> MagicMock:
    conn = MagicMock()
    conn.closed = 0
    conn.info.transaction_status = extensions.TRANSACTION_STATUS_IDLE
    return conn


# --- URL validation (now enforced at pool build, still reachable from get_connection) ---

def test_get_connection_rejects_non_postgresql_url(monkeypatch):
    monkeypatch.setattr("services.db.pool.DATABASE_URL", "mysql://localhost/agent_smith")
    with pytest.raises(ValueError, match="DATABASE_URL must be a postgresql:// URL"):
        with get_connection():
            pass


def test_get_connection_rejects_sqlite_url(monkeypatch):
    monkeypatch.setattr("services.db.pool.DATABASE_URL", "sqlite:///tmp/test.db")
    with pytest.raises(ValueError, match="DATABASE_URL must be a postgresql:// URL"):
        with get_connection():
            pass


# --- transaction contract: commit on success, rollback on error, connection returned ---

def test_commits_and_returns_connection_on_success(monkeypatch):
    conn = _live_conn()
    release = MagicMock()
    monkeypatch.setattr(conn_mod.pool, "acquire", lambda: conn)
    monkeypatch.setattr(conn_mod.pool, "release", release)

    with get_connection() as c:
        assert c is conn

    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    release.assert_called_once_with(conn, close=False)


def test_rolls_back_and_returns_connection_on_ordinary_error(monkeypatch):
    conn = _live_conn()
    release = MagicMock()
    monkeypatch.setattr(conn_mod.pool, "acquire", lambda: conn)
    monkeypatch.setattr(conn_mod.pool, "release", release)

    with pytest.raises(RuntimeError):
        with get_connection():
            raise RuntimeError("boom")

    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    release.assert_called_once_with(conn, close=False)


# --- dead-connection invalidation: a broken connection is discarded, not re-pooled ---

def test_connection_level_error_discards_connection(monkeypatch):
    conn = _live_conn()
    release = MagicMock()
    monkeypatch.setattr(conn_mod.pool, "acquire", lambda: conn)
    monkeypatch.setattr(conn_mod.pool, "release", release)

    with pytest.raises(psycopg2.OperationalError):
        with get_connection():
            raise psycopg2.OperationalError("server closed the connection unexpectedly")

    release.assert_called_once_with(conn, close=True)


def test_closed_connection_is_discarded(monkeypatch):
    conn = _live_conn()
    conn.commit.side_effect = lambda: setattr(conn, "closed", 1)
    release = MagicMock()
    monkeypatch.setattr(conn_mod.pool, "acquire", lambda: conn)
    monkeypatch.setattr(conn_mod.pool, "release", release)

    with get_connection():
        pass

    release.assert_called_once_with(conn, close=True)


def test_throwing_commit_raises_and_discards(monkeypatch):
    conn = _live_conn()
    conn.commit.side_effect = psycopg2.OperationalError("server closed the connection")
    release = MagicMock()
    monkeypatch.setattr(conn_mod.pool, "acquire", lambda: conn)
    monkeypatch.setattr(conn_mod.pool, "release", release)

    with pytest.raises(psycopg2.OperationalError):
        with get_connection():
            pass

    release.assert_called_once_with(conn, close=True)


def test_throwing_rollback_still_releases_and_discards(monkeypatch):
    """A connection-level error during rollback must not skip the finally: the
    connection is still returned (with close=True) so its pool slot is freed."""
    conn = _live_conn()
    conn.rollback.side_effect = psycopg2.InterfaceError("connection already closed")
    release = MagicMock()
    monkeypatch.setattr(conn_mod.pool, "acquire", lambda: conn)
    monkeypatch.setattr(conn_mod.pool, "release", release)

    with pytest.raises(RuntimeError):
        with get_connection():
            raise RuntimeError("boom")

    release.assert_called_once_with(conn, close=True)


# --- pool acquisition resilience (services/db/pool.py) ---

def test_retrying_succeeds_after_transient(monkeypatch):
    monkeypatch.setattr(pool_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(pool_mod, "DB_CONNECT_MAX_ATTEMPTS", 3)
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        if calls["n"] < 3:
            raise psycopg2.OperationalError("connection refused")
        return "ok"

    assert pool_mod._retrying("x", factory) == "ok"
    assert calls["n"] == 3


def test_retrying_raises_after_exhaustion(monkeypatch):
    monkeypatch.setattr(pool_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(pool_mod, "DB_CONNECT_MAX_ATTEMPTS", 3)
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        raise psycopg2.OperationalError("refused")

    with pytest.raises(psycopg2.OperationalError):
        pool_mod._retrying("x", factory)
    assert calls["n"] == 3


def test_acquire_discards_stale_then_returns_live(monkeypatch):
    monkeypatch.setattr(pool_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(pool_mod, "DB_POOL_PRE_PING", False)
    stale = MagicMock(closed=1)
    live = MagicMock(closed=0)
    fake_pool = MagicMock()
    fake_pool.getconn.side_effect = [stale, live]
    monkeypatch.setattr(pool_mod, "_get_pool", lambda: fake_pool)

    assert pool_mod.acquire() is live
    fake_pool.putconn.assert_called_once_with(stale, close=True)


def test_acquire_does_not_retry_pool_exhaustion(monkeypatch):
    fake_pool = MagicMock()
    fake_pool.getconn.side_effect = PoolError("connection pool exhausted")
    monkeypatch.setattr(pool_mod, "_get_pool", lambda: fake_pool)

    with pytest.raises(PoolError):
        pool_mod.acquire()
    fake_pool.getconn.assert_called_once()  # fail-fast, no backoff loop


def test_acquire_pre_ping_replaces_bad_connection(monkeypatch):
    monkeypatch.setattr(pool_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(pool_mod, "DB_POOL_PRE_PING", True)

    bad = MagicMock(closed=0)
    bad.cursor.return_value.__enter__.return_value.execute.side_effect = \
        psycopg2.OperationalError("dead")
    good = MagicMock(closed=0)
    good_cur = good.cursor.return_value.__enter__.return_value
    good_cur.execute.return_value = None
    good_cur.fetchone.return_value = (1,)

    fake_pool = MagicMock()
    fake_pool.getconn.side_effect = [bad, good]
    monkeypatch.setattr(pool_mod, "_get_pool", lambda: fake_pool)

    assert pool_mod.acquire() is good
    fake_pool.putconn.assert_called_once_with(bad, close=True)


# --- regression guard for minconn == maxconn: pooled connections are REUSED ---
# (real test-db). With the minconn=0 bug, every checkout would reconnect and the
# backend PIDs would differ.

def test_pooled_connection_is_reused(monkeypatch):
    monkeypatch.setattr(pool_mod, "DB_POOL_MAX", 2)
    pool_mod.close_pool()

    def backend_pid() -> int:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_backend_pid()")
                return cur.fetchone()[0]

    first = backend_pid()
    second = backend_pid()
    assert first == second, "pool should reuse the same backend, not reconnect"
