from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.models.proposal import get_proposal
from services.api.routers import jobs as router_module
from services.db import get_connection
from services.jobs import scheduler, server
from services.jobs.models import execution as execution_model
from services.jobs.models.config import create_config, list_configs
from services.jobs.models.execution import (
    complete_execution,
    create_execution,
    get_execution,
    list_executions_for_job,
)
from services.jobs.models.job import create_job, get_job, set_schedule_enabled
from services.proposals.service import persist_proposal, reject_proposal, stage_proposal
from tests.conftest import jobs_cleanup
from tests.jobs.test_scheduling_runtime import database_blocked_by

_clean = jobs_cleanup("JOBADMISSION %")


@pytest.fixture(autouse=True)
def clean_proposals():
    yield
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM improvement_proposals WHERE target_name LIKE 'JOBADMISSION %'"
        )


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/jobs")
    return TestClient(app)


@pytest.fixture(autouse=True)
def forbidden_runners(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("An inactive job reached an external execution path")

    monkeypatch.setattr(scheduler, "_run_command_job", forbidden)
    monkeypatch.setattr(scheduler, "_run_graph_job", forbidden)


def params(kind):
    if kind == "command":
        return {"command": "synthetic command must not execute"}
    return {
        "graph_type": "echo",
        "graph_inputs": {"text": "synthetic graph must not execute"},
    }


def active_job(kind="command"):
    return get_job(
        create_job("JOBADMISSION " + uuid4().hex, {"minutes": 5}, params(kind))
    )


def inactive_job(kind, state):
    proposal_id = persist_proposal(
        stage_proposal(
            {
                "target_kind": "job",
                "action": "create",
                "target_name": "JOBADMISSION " + uuid4().hex,
                "title": "Synthetic unapproved job",
                "rationale": "Characterize execution admission before approval",
                "schedule_config": {"minutes": 5},
                "input_params": params(kind),
            }
        )
    )
    if state == "rejected":
        reject_proposal(proposal_id)
    return get_job(get_proposal(proposal_id)["proposed_item_id"])


def set_state(job_id, state):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE background_jobs SET state=%s WHERE id=%s", (state, job_id))


async def invoke(entrypoint, selected, client):
    if entrypoint == "rest":
        response = client.post(f"/api/jobs/{selected['id']}/run-now")
        assert response.status_code == 200
        return response.json()
    if entrypoint == "mcp":
        return await server.job_run_now(selected["id"])
    return await scheduler.execute_job(selected)


def assert_rejected(result, job_id):
    assert result["success"] is False
    assert "not active" in result["error"].lower()
    assert "execution_id" not in result
    assert list_executions_for_job(job_id) == ([], 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["rest", "mcp", "direct"])
@pytest.mark.parametrize("kind", ["command", "graph"])
@pytest.mark.parametrize("state", ["proposed", "rejected"])
@pytest.mark.parametrize("stale_snapshot", [False, True])
async def test_active_admission_rejects_inactive_jobs_before_any_runner(
    client, entrypoint, kind, state, stale_snapshot
):
    selected = active_job(kind) if stale_snapshot else inactive_job(kind, state)
    if stale_snapshot:
        set_state(selected["id"], state)
    before = get_job(selected["id"])
    result = await invoke(entrypoint, selected, client)
    assert_rejected(result, selected["id"])
    assert get_job(selected["id"]) == before


@pytest.mark.parametrize("state", ["proposed", "rejected"])
@pytest.mark.parametrize("automatic", [False, True])
def test_active_admission_model_rejects_inactive_rows(state, automatic):
    selected = inactive_job("command", state)
    assert create_execution(selected["id"], automatic=automatic) is None
    assert list_executions_for_job(selected["id"]) == ([], 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["rest", "mcp", "direct"])
@pytest.mark.parametrize("kind", ["command", "graph"])
@pytest.mark.parametrize("paused", [False, True])
async def test_active_admission_allows_direct_created_jobs_and_manual_pause_override(
    client, monkeypatch, entrypoint, kind, paused
):
    selected = active_job(kind)
    assert selected["state"] == "active"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM improvement_proposals WHERE target_kind='job' AND proposed_item_id=%s",
            (selected["id"],),
        )
        assert cur.fetchone()[0] == 0
    if paused:
        set_schedule_enabled(selected["id"], False)
    create_config(
        selected["id"], device="different-device", repo="different-repo", enabled=False
    )
    before, configs = get_job(selected["id"]), list_configs(selected["id"])
    calls = []

    async def synthetic(execution_id, job_id, definition, input_params):
        calls.append((job_id, definition, input_params))
        result = {
            "success": True,
            "output": "synthetic success",
            "error": "",
            "duration_seconds": 0,
            "exit_code": 0,
        }
        complete_execution(execution_id, "success", result)
        return result

    monkeypatch.setattr(
        scheduler,
        "_run_command_job" if kind == "command" else "_run_graph_job",
        synthetic,
    )
    result = await invoke(entrypoint, selected, client)
    assert result["success"] is True
    assert (
        len(calls) == 1
        and calls[0][0] == selected["id"]
        and calls[0][2] == selected["input_params"]
    )
    assert get_execution(result["execution_id"])["status"] == "success"
    assert list_executions_for_job(selected["id"])[1] == 1
    assert get_job(selected["id"]) == before and list_configs(selected["id"]) == configs


@pytest.mark.parametrize("state", ["proposed", "rejected"])
def test_active_admission_waits_for_current_state_before_recording_manual_execution(
    monkeypatch, state
):
    selected = active_job()
    entered = threading.Event()
    backend = []

    @contextmanager
    def tracked_connection():
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout='10s'")
            backend.append(conn.get_backend_pid())
            entered.set()
            yield conn

    monkeypatch.setattr(execution_model, "get_connection", tracked_connection)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with get_connection() as blocker, blocker.cursor() as cur:
            cur.execute(
                "UPDATE background_jobs SET state=%s WHERE id=%s",
                (state, selected["id"]),
            )
            pending = pool.submit(asyncio.run, scheduler.execute_job(selected))
            assert entered.wait(timeout=3)
            database_blocked_by(backend[0], blocker.get_backend_pid())
            assert not pending.done()
        result = pending.result(timeout=5)
    assert_rejected(result, selected["id"])
