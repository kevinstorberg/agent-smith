"""The database transaction contract: ``get_connection()``.

This is the single boundary every DB caller funnels through. It is intentionally
small — acquire a connection, yield it inside a transaction, commit on success /
roll back on failure, and always return the connection to the pool. The pooling,
retry/backoff, and libpq tuning live in ``services.db.pool``; this file keeps the
contract that ~80 call sites depend on unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager

import psycopg2
from psycopg2 import extensions

from services.config import DATABASE_URL  # noqa: F401 - re-exported for back-compat
from services.db import pool

# Connection-level failures mean the connection itself is dead and must not be
# returned to the pool. Ordinary SQL errors (IntegrityError, ProgrammingError)
# leave a healthy connection that should be reused after a rollback.
_CONN_LEVEL_ERRORS = (psycopg2.OperationalError, psycopg2.InterfaceError)


def _is_broken(conn, exc: BaseException | None = None) -> bool:
    if conn.closed:
        return True
    if exc is not None and isinstance(exc, _CONN_LEVEL_ERRORS):
        return True
    try:
        return conn.info.transaction_status == extensions.TRANSACTION_STATUS_UNKNOWN
    except Exception:
        return True


def _safe_commit(conn) -> BaseException | None:
    try:
        conn.commit()
        return None
    except _CONN_LEVEL_ERRORS as exc:
        return exc


def _safe_rollback(conn) -> BaseException | None:
    try:
        conn.rollback()
        return None
    except _CONN_LEVEL_ERRORS as exc:
        return exc


@contextmanager
def get_connection():
    conn = pool.acquire()
    failure: BaseException | None = None
    try:
        try:
            yield conn
        except Exception as exc:
            failure = _safe_rollback(conn) or exc
            raise
        else:
            commit_err = _safe_commit(conn)
            if commit_err is not None:
                failure = commit_err
                raise commit_err
    finally:
        pool.release(conn, close=_is_broken(conn, failure))
