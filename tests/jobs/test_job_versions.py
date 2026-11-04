from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from services.api.models import base as base_model
from services.db import get_connection
from services.jobs.models import job as job_model
from services.jobs.models.job import create_job, get_job, update_job
from tests.conftest import jobs_cleanup

_clean = jobs_cleanup("JOBVERSION %")


@pytest.fixture
def writers(monkeypatch):
    backends = {}
    labels = threading.local()

    @contextmanager
    def tracked_connection():
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '10s'")
                cur.execute("SET LOCAL statement_timeout = '12s'")
            label = getattr(labels, "name", None)
            if label is not None:
                backends[label] = conn.get_backend_pid()
            yield conn

    monkeypatch.setattr(base_model, "get_connection", tracked_connection)
    monkeypatch.setattr(job_model, "get_connection", tracked_connection)

    def write(label, job_id, **fields):
        labels.name = label
        update_job(job_id, **fields)

    def wait_for_blocked_writers(blocker, pending):
        deadline = time.monotonic() + 5
        observed = {}
        while time.monotonic() < deadline:
            with blocker.cursor() as cur:
                for label, future in pending.items():
                    if future.done():
                        future.result()
                        pytest.fail(
                            f"Writer {label} bypassed the held PostgreSQL job row lock"
                        )
                    backend = backends.get(label)
                    if backend is not None:
                        cur.execute("SELECT pg_blocking_pids(%s)", (backend,))
                        observed[label] = cur.fetchone()[0]
            if len(observed) == len(pending) and all(observed.values()):
                return
            time.sleep(0.01)
        pytest.fail(f"Native PostgreSQL writer waits were not observed: {observed}")

    return write, wait_for_blocked_writers


def job(suffix):
    return create_job(
        "JOBVERSION " + suffix,
        {"minutes": 5},
        {"command": "never executed"},
        "Original description",
    )


def lock_job(conn, job_id):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM background_jobs WHERE id=%s FOR UPDATE", (job_id,))


def test_job_versions_count_both_concurrent_definition_writes(writers):
    job_id = job("two definitions")
    before = get_job(job_id)
    write, wait = writers
    with ThreadPoolExecutor(max_workers=2) as pool:
        with get_connection() as blocker:
            lock_job(blocker, job_id)
            pending = {
                "description": pool.submit(
                    write, "description", job_id, description="Changed description"
                ),
                "schedule": pool.submit(
                    write, "schedule", job_id, schedule_config={"hours": 2}
                ),
            }
            wait(blocker, pending)
        for future in pending.values():
            future.result(timeout=5)
    updated = get_job(job_id)
    assert updated["version"] == before["version"] + 2
    assert updated["description"] == "Changed description"
    assert updated["schedule_config"] == {"hours": 2}
    assert updated["input_params"] == before["input_params"]


def test_job_versions_definition_cannot_reverse_intervening_atomic_increments(writers):
    job_id = job("intervening changes")
    before = get_job(job_id)
    write, wait = writers
    with ThreadPoolExecutor(max_workers=1) as pool:
        with get_connection() as blocker:
            lock_job(blocker, job_id)
            pending = pool.submit(
                write, "definition", job_id, description="Latest description"
            )
            wait(blocker, {"definition": pending})
            with blocker.cursor() as cur:
                for enabled in (False, True):
                    cur.execute(
                        "UPDATE background_jobs SET schedule_enabled=%s, version=version+1 WHERE id=%s",
                        (enabled, job_id),
                    )
        pending.result(timeout=5)
    updated = get_job(job_id)
    assert updated["version"] == before["version"] + 3
    assert updated["description"] == "Latest description"
    assert updated["schedule_enabled"] is True
