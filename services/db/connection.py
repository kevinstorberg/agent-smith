from __future__ import annotations

from contextlib import contextmanager

import psycopg2

from services.config import DATABASE_URL
from scripts.shared.validation import validate_postgres_url


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
