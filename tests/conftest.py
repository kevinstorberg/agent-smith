from __future__ import annotations

import os

from scripts.shared.automated_tests import activate_automated_tests

activate_automated_tests()
os.environ["APP_ENV"] = "test"

import pytest


@pytest.fixture
def extraction_only(monkeypatch):
    from services.personas.service import PersonaRun

    async def skip_assessment(self):
        return None

    monkeypatch.setattr(PersonaRun, "build_assessments", skip_assessment)


@pytest.fixture(scope="session", autouse=True)
def _setup_test_db():
    from services.db.create import create_database
    from services.config import APP_ENV, DATABASE_URL
    from services.db import init_db

    if APP_ENV != "test":
        raise RuntimeError("Backend tests cannot use an application configured outside APP_ENV=test")
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


def clean_job_rows(*patterns: str):
    from services.db import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            for pattern in patterns:
                cur.execute("DELETE FROM background_jobs WHERE name LIKE %s", (pattern,))


def jobs_cleanup(*patterns: str):
    @pytest.fixture(autouse=True)
    def _clean():
        yield
        clean_job_rows(*patterns)
    return _clean


def clean_meeting_rows(account_key: str):
    from services.db import get_connection
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meeting_summaries WHERE account_key = %s", (account_key,))
        cur.execute("DELETE FROM meeting_sync_state WHERE account_key = %s", (account_key,))


@pytest.fixture
def unidentified_speakers(monkeypatch):
    from services.meetings import speaker_analysis

    async def no_assignments(*args, **kwargs):
        return {"assignments": [], "reason": "No grounded speaker identity"}

    monkeypatch.setattr(speaker_analysis, "identify_statements", no_assignments)


def clean_audit_rows(*patterns: str):
    from services.db import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            for pattern in patterns:
                cur.execute("DELETE FROM tool_call_events WHERE session_id LIKE %s", (pattern,))


def audit_cleanup(*patterns: str):
    @pytest.fixture(autouse=True)
    def _clean():
        yield
        clean_audit_rows(*patterns)
    return _clean
