from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2

from scripts.shared.validation import validate_postgres_url

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/agent_smith")


@contextmanager
def get_connection():
    validate_postgres_url(DATABASE_URL)
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
