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
