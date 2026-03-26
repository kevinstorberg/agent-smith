from __future__ import annotations

import pytest


def postgres_available() -> bool:
    try:
        from services.db.connection import DATABASE_URL
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        return True
    except Exception:
        return False
