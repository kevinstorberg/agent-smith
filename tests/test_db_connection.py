from __future__ import annotations

import contextlib
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
    monkeypatch.setattr(
        "services.db.pool.DATABASE_URL", "mysql://localhost/agent_smith"
    )
    with pytest.raises(ValueError, match="DATABASE_URL must be a postgresql:// URL"):
        with get_connection():
            pass


def test_get_connection_rejects_sqlite_url(monkeypatch):
    monkeypatch.setattr("services.db.pool.DATABASE_URL", "sqlite:///tmp/test.db")
    with pytest.raises(ValueError, match="DATABASE_URL must be a postgresql:// URL"):
        with get_connection():
            pass


@pytest.mark.parametrize("maximum", [0, -1, True, False, 1.5, "3", None])
def test_invalid_pool_ceiling_fails_before_connection_io(monkeypatch, maximum):
    monkeypatch.setattr(pool_mod, "DB_POOL_MAX", maximum)

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid pool ceiling reached connection construction")

    monkeypatch.setattr(pool_mod.pg_pool, "ThreadedConnectionPool", forbidden)
    monkeypatch.setattr(psycopg2, "connect", forbidden)
    with pytest.raises(ValueError, match="DB_POOL_MAX must be a positive integer"):
        pool_mod.init_pool()
    assert pool_mod._pool is None


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
    bad.cursor.return_value.__enter__.return_value.execute.side_effect = (
        psycopg2.OperationalError("dead")
    )
    good = MagicMock(closed=0)
    good_cur = good.cursor.return_value.__enter__.return_value
    good_cur.execute.return_value = None
    good_cur.fetchone.return_value = (1,)

    fake_pool = MagicMock()
    fake_pool.getconn.side_effect = [bad, good]
    monkeypatch.setattr(pool_mod, "_get_pool", lambda: fake_pool)

    assert pool_mod.acquire() is good
    fake_pool.putconn.assert_called_once_with(bad, close=True)


def test_acquire_drains_all_stale_in_one_call(monkeypatch):
    """A sleep/partition can leave the whole free list dead. One acquire() must
    drain ALL of them (not just the connect-retry budget) and return a live one."""
    monkeypatch.setattr(pool_mod, "DB_POOL_PRE_PING", False)
    monkeypatch.setattr(
        pool_mod, "DB_CONNECT_MAX_ATTEMPTS", 3
    )  # < number of stale conns
    stale = [MagicMock(closed=1) for _ in range(5)]
    live = MagicMock(closed=0)
    fake_pool = MagicMock()
    fake_pool.getconn.side_effect = [*stale, live]
    monkeypatch.setattr(pool_mod, "_get_pool", lambda: fake_pool)

    assert pool_mod.acquire() is live
    assert fake_pool.putconn.call_count == 5  # every stale conn discarded in one call


def test_acquire_retries_connect_failure_then_raises(monkeypatch):
    monkeypatch.setattr(pool_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(pool_mod, "DB_CONNECT_MAX_ATTEMPTS", 3)
    fake_pool = MagicMock()
    fake_pool.getconn.side_effect = psycopg2.OperationalError("connection refused")
    monkeypatch.setattr(pool_mod, "_get_pool", lambda: fake_pool)

    with pytest.raises(psycopg2.OperationalError):
        pool_mod.acquire()
    assert fake_pool.getconn.call_count == 3  # bounded backoff retry


# --- mass-staleness: a connection-level error purges the idle pool ---


def test_connection_level_error_drains_idle_pool(monkeypatch):
    conn = _live_conn()
    drain = MagicMock()
    monkeypatch.setattr(conn_mod.pool, "acquire", lambda: conn)
    monkeypatch.setattr(conn_mod.pool, "release", MagicMock())
    monkeypatch.setattr(conn_mod.pool, "drain_idle", drain)

    with pytest.raises(psycopg2.OperationalError):
        with get_connection():
            raise psycopg2.OperationalError("SSL SYSCALL error: EOF detected")

    drain.assert_called_once()


def test_ordinary_sql_error_does_not_drain_idle_pool(monkeypatch):
    conn = _live_conn()
    drain = MagicMock()
    monkeypatch.setattr(conn_mod.pool, "acquire", lambda: conn)
    monkeypatch.setattr(conn_mod.pool, "release", MagicMock())
    monkeypatch.setattr(conn_mod.pool, "drain_idle", drain)

    with pytest.raises(psycopg2.IntegrityError):
        with get_connection():
            raise psycopg2.IntegrityError("duplicate key value")

    drain.assert_not_called()


# --- end-to-end: the whole pool goes stale, recovery costs ONE failed op ---


def test_mass_stale_pool_recovers_after_one_failure(monkeypatch):
    monkeypatch.setattr(pool_mod, "DB_POOL_MAX", 3)
    pool_mod.close_pool()

    # Warm the pool, then return every connection to the free list.
    pids, conns = set(), []
    for _ in range(3):
        c = pool_mod.acquire()
        with c.cursor() as cur:
            cur.execute("SELECT pg_backend_pid()")
            pids.add(cur.fetchone()[0])
        conns.append(c)
    for c in conns:
        pool_mod.release(c, close=False)
    retained_pids = {c.get_backend_pid() for c in conns if not c.closed}
    assert len(retained_pids) == 1

    # Simulate sleep: kill every backend the pool is holding.
    admin = psycopg2.connect(pool_mod.DATABASE_URL)
    admin.autocommit = True
    with admin.cursor() as cur:
        for pid in retained_pids:
            cur.execute("SELECT pg_terminate_backend(%s)", (pid,))
    admin.close()

    # The next op may fail once (a stale conn handed out before detection); that
    # failure drains the rest of the now-dead pool.
    with contextlib.suppress(psycopg2.Error):
        with get_connection() as c:
            with c.cursor() as cur:
                cur.execute("SELECT 1")

    # Recovery must now be immediate on a fresh backend — not 3 more failures.
    with get_connection() as c:
        with c.cursor() as cur:
            cur.execute("SELECT pg_backend_pid()")
            new_pid = cur.fetchone()[0]
    assert new_pid not in pids
    pool_mod.close_pool()


# --- one retained connection preserves serial pooling ---
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


@pytest.fixture
def counted_connections(monkeypatch):
    connect = psycopg2.connect
    created = []

    def tracked_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        created.append(connection)
        return connection

    monkeypatch.setattr(psycopg2, "connect", tracked_connect)
    yield created
    pool_mod.close_pool()
    assert all(connection.closed for connection in created)


def test_startup_opens_one_real_connection_without_reserving_peak(
    monkeypatch, counted_connections
):
    monkeypatch.setattr(pool_mod, "DB_POOL_MAX", 25)
    pool_mod.init_pool()
    assert len(counted_connections) == 1
    assert not counted_connections[0].closed
    with get_connection() as connection:
        assert connection is counted_connections[0]
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)
    assert len(counted_connections) == 1


def test_real_pool_grows_to_ceiling_then_returns_to_one_warm_connection(
    monkeypatch, counted_connections
):
    monkeypatch.setattr(pool_mod, "DB_POOL_MAX", 3)
    connections = [pool_mod.acquire() for _ in range(3)]
    try:
        assert len(counted_connections) == 3
        assert len({connection.get_backend_pid() for connection in connections}) == 3
        with pytest.raises(PoolError, match="connection pool exhausted"):
            pool_mod.acquire()
        assert len(counted_connections) == 3
    finally:
        for connection in connections:
            pool_mod.release(connection, close=False)

    assert sum(not connection.closed for connection in counted_connections) == 1
    assert not connections[0].closed
    assert all(connection.closed for connection in connections[1:])
    with get_connection() as connection:
        assert connection is connections[0]
    assert len(counted_connections) == 3


def test_real_pool_construction_retries_then_opens_only_one_connection(monkeypatch):
    monkeypatch.setattr(pool_mod, "DB_POOL_MAX", 3)
    monkeypatch.setattr(pool_mod, "DB_CONNECT_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(pool_mod.time, "sleep", lambda seconds: None)
    connect = psycopg2.connect
    calls, connections = [], []

    def flaky_connect(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) < 3:
            raise psycopg2.OperationalError("Synthetic connection refusal")
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(psycopg2, "connect", flaky_connect)
    pool_mod.init_pool()
    assert len(calls) == 3 and len(connections) == 1
    assert all(call == pool_mod._connect_kwargs() for call in calls)
    with get_connection() as connection:
        assert connection is connections[0]
    pool_mod.close_pool()
    assert connections[0].closed


def test_failed_pool_construction_remains_uncached_and_retries_are_bounded(monkeypatch):
    monkeypatch.setattr(pool_mod, "DB_CONNECT_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(pool_mod.time, "sleep", lambda seconds: None)
    connect = MagicMock(side_effect=psycopg2.OperationalError("Synthetic refusal"))
    monkeypatch.setattr(psycopg2, "connect", connect)

    with pytest.raises(psycopg2.OperationalError, match="Synthetic refusal"):
        pool_mod.init_pool()
    assert connect.call_count == 3
    assert pool_mod._pool is None
