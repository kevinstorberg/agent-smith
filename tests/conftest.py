from __future__ import annotations

import os

os.environ["APP_ENV"] = "test"

import pytest


@pytest.fixture(scope="session", autouse=True)
def _setup_test_db():
    from services.db.create import create_database
    from services.config import DATABASE_URL
    from services.db import init_db

    create_database(DATABASE_URL)
    init_db()

    from tests.seeds import seed_test_data
    seed_test_data()


HARNESS_TABLES = [
    ("harness_rules", "rule"),
    ("harness_skills", "skill"),
    ("harness_tools", "tool"),
    ("harness_hooks", "hook"),
    ("harness_agents", "agent"),
]


def clean_harness_rows(*patterns: str):
    from services.db import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            for table, item_type in HARNESS_TABLES:
                for pattern in patterns:
                    cur.execute(
                        f"DELETE FROM harness_configs WHERE item_type = %s AND item_id IN (SELECT id FROM {table} WHERE name LIKE %s)",
                        (item_type, pattern),
                    )
                    cur.execute(f"DELETE FROM {table} WHERE name LIKE %s", (pattern,))


def harness_cleanup(*patterns: str):
    @pytest.fixture(autouse=True)
    def _clean():
        yield
        clean_harness_rows(*patterns)
    return _clean
