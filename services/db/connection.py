from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/agent_smith")


@contextmanager
def get_connection():
    if not DATABASE_URL.startswith(("postgresql://", "postgres://")):
        raise ValueError(
            f"DATABASE_URL must be a postgresql:// URL, got: {DATABASE_URL[:20]}..."
        )
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
