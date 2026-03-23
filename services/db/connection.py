from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2

DATABASE_URL = os.environ.get("EVAL_DATABASE_URL", "postgresql://localhost/agent_smith")


@contextmanager
def get_connection():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
