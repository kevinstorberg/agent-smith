"""Thread-safe psycopg2 connection pool with bounded transient-error retry.

This is the resilience machinery behind ``services.db.connection.get_connection``.
It is deliberately separate from ``connection.py`` so that file stays a small,
reviewable statement of the transaction contract while the pool lifecycle,
retry/backoff, and libpq tuning live here.

Why a fixed-size pool (``minconn == maxconn``): psycopg2's
``AbstractConnectionPool._putconn`` only returns a connection to the free list
when ``len(self._pool) < self.minconn``. With ``minconn == maxconn`` every
returned connection is retained and stays warm; with ``minconn=0`` every
returned connection would be closed, defeating pooling entirely.

The pool is built lazily on first use (inside the retry helper), so the app can
start and serve even while the database is briefly unreachable, and a blip
during pool construction is retried rather than crashing the process.
"""
from __future__ import annotations

import logging
import threading
import time

import psycopg2
from psycopg2 import pool as pg_pool

from services.config import (
    DATABASE_URL,
    DB_CONNECT_BACKOFF_BASE,
    DB_CONNECT_BACKOFF_MAX,
    DB_CONNECT_MAX_ATTEMPTS,
    DB_CONNECT_TIMEOUT,
    DB_POOL_MAX,
    DB_POOL_PRE_PING,
)
from scripts.shared.validation import validate_postgres_url

log = logging.getLogger("db.pool")

# A transient connection failure: worth retrying because the next attempt may
# reach a recovered server. InterfaceError covers a connection used after the
# server went away; OperationalError covers connect-time refusals/resets.
_TRANSIENT = (psycopg2.OperationalError, psycopg2.InterfaceError)

_pool: pg_pool.ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _connect_kwargs() -> dict:
    """libpq connection options applied to every pooled connection.

    ``connect_timeout`` bounds each attempt so a black-holed host fails fast
    instead of hanging for the OS default. TCP keepalives let the kernel detect
    a dead idle socket (e.g. after an RDS failover) so it surfaces promptly as
    ``conn.closed`` rather than a multi-minute black hole.
    """
    return {
        "connect_timeout": int(DB_CONNECT_TIMEOUT),
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
    }


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with a small deterministic jitter, capped.

    ``attempt`` is 1-based. Jitter is derived from the attempt (not a RNG) so
    behaviour stays test-friendly while still de-synchronising retriers.
    """
    raw = DB_CONNECT_BACKOFF_BASE * (2 ** (attempt - 1))
    jitter = DB_CONNECT_BACKOFF_BASE * 0.1 * (attempt % 3)
    return min(raw + jitter, DB_CONNECT_BACKOFF_MAX)


def _retrying(what: str, factory):
    """Call ``factory`` with bounded retry on transient connection errors.

    Used for both pool construction and connection acquisition: in both cases
    no SQL statement has executed yet, so retrying cannot replay a
    non-idempotent operation. Raises the last error once attempts are exhausted
    so a genuinely-down database surfaces loudly to the caller.
    """
    last: Exception | None = None
    for attempt in range(1, DB_CONNECT_MAX_ATTEMPTS + 1):
        try:
            return factory()
        except _TRANSIENT as exc:
            last = exc
            if attempt < DB_CONNECT_MAX_ATTEMPTS:
                delay = _backoff_delay(attempt)
                log.warning("%s failed (attempt %d/%d), retrying in %.2fs: %s",
                            what, attempt, DB_CONNECT_MAX_ATTEMPTS, delay, exc)
                time.sleep(delay)
    assert last is not None
    raise last


def _build_pool() -> pg_pool.ThreadedConnectionPool:
    validate_postgres_url(DATABASE_URL)
    return _retrying(
        "db pool construction",
        lambda: pg_pool.ThreadedConnectionPool(
            DB_POOL_MAX, DB_POOL_MAX, DATABASE_URL, **_connect_kwargs()
        ),
    )


def _get_pool() -> pg_pool.ThreadedConnectionPool:
    """Return the process-wide pool, constructing it once on first use.

    Double-checked locking: the lock-free read is the hot path; construction
    happens once under the lock. ``_pool`` is only assigned to a fully-built
    pool, so a failed construction leaves it ``None`` for the next caller to
    retry rather than caching a half-built pool.
    """
    global _pool
    p = _pool
    if p is None:
        with _pool_lock:
            if _pool is None:
                _pool = _build_pool()
            p = _pool
    return p


def acquire() -> "psycopg2.extensions.connection":
    """Check out a live connection, handling two distinct failure modes.

    - A *stale* pooled connection (already closed, or failing an opt-in
      pre-ping) is discarded and the next one tried immediately with no backoff.
      Because each discard shrinks the free list, this drains every dead pooled
      connection in a single call — so a sleep/partition that severed the whole
      pool costs one drain, not one failed op per connection.
    - A genuine *connect* failure (free list empty, server unreachable) is
      retried with bounded exponential backoff, then raised so a truly-down
      database surfaces loudly. Pool exhaustion (PoolError) is not transient and
      surfaces immediately.
    """
    pool = _get_pool()
    connect_attempts = 0
    while True:
        try:
            conn = pool.getconn()
        except _TRANSIENT:
            connect_attempts += 1
            if connect_attempts >= DB_CONNECT_MAX_ATTEMPTS:
                raise
            log.warning("db connect failed (attempt %d/%d), backing off",
                        connect_attempts, DB_CONNECT_MAX_ATTEMPTS)
            time.sleep(_backoff_delay(connect_attempts))
            continue
        if conn.closed or (DB_POOL_PRE_PING and not _ping_ok(conn)):
            pool.putconn(conn, close=True)
            continue
        return conn


def release(conn, *, close: bool) -> None:
    """Return a connection to the pool, discarding it (``close=True``) when broken
    so the pool never re-hands a dead connection. Always frees the capacity slot."""
    _get_pool().putconn(conn, close=close)


def drain_idle() -> None:
    """Close and discard every idle (checked-in) pooled connection.

    Recovers from a *mass*-staleness event — a laptop sleep or network partition
    silently severs every pooled connection at once. When one in-use connection
    fails with a connection-level error, the rest of the free list is almost
    certainly dead too; purging it here means the next checkout reconnects fresh
    instead of handing out 25 more dead sockets one failed op at a time. In-use
    connections (owned by other threads) are left untouched and recover on their
    own exit. Held under the pool's own lock so it cannot race getconn/putconn.
    """
    p = _pool
    if p is None:
        return
    with p._lock:
        while p._pool:
            try:
                p._pool.pop().close()
            except Exception:
                pass


def _ping_ok(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except _TRANSIENT:
        return False


def init_pool() -> None:
    """Eagerly build the pool (called from the app lifespan after migrations)."""
    _get_pool()


def close_pool() -> None:
    """Close all pooled connections and reset state. Idempotent."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            finally:
                _pool = None
