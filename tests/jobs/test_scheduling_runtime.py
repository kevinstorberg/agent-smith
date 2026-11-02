import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.models.base import BaseModel
from services.api.routers import jobs as router_module
from services.db import get_connection
from services.jobs import scheduler as scheduler_module, server
from services.jobs.models import execution as execution_model, job as job_model
from services.jobs.models.config import create_config, list_configs
from services.jobs.models.execution import create_execution, get_execution, list_executions_for_job
from services.jobs.models.job import create_job, get_job, set_schedule_enabled
from services.jobs.scheduler import JobScheduler, execute_job
from tests.conftest import jobs_cleanup
from tests.test_manual_analysis import jobs as jobs, payload as payload, saved as saved
from tests.test_meeting_sync import source as source

_clean = jobs_cleanup("SCHEDULINGTEST %")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/jobs")
    return TestClient(app)


def job():
    job_id = create_job("SCHEDULINGTEST " + uuid4().hex, {"minutes": 15}, {"command": "echo scheduling-test"})
    create_config(job_id, device="*", repo="*", enabled=True)
    return get_job(job_id)


def database_blocked_by(waiter: int, blocker: int) -> None:
    deadline = time.monotonic() + 3
    with get_connection() as conn, conn.cursor() as cur:
        while time.monotonic() < deadline:
            cur.execute("SELECT %s=ANY(pg_blocking_pids(%s))", (blocker, waiter))
            if cur.fetchone()[0]:
                return
            time.sleep(0.01)
    raise AssertionError("The expected PostgreSQL row-lock wait was not observed")


def test_scheduling_patch_is_narrow_and_keeps_other_jobs_and_configs(client):
    selected, other = job(), job()
    create_config(selected["id"], device="excluded-device", repo="special", enabled=False, exclude=True)
    configs = list_configs(selected["id"])
    response = client.patch(f"/api/jobs/{selected['id']}/scheduling", json={"schedule_enabled": False})
    assert response.status_code == 200
    acknowledged = response.json()
    assert acknowledged["schedule_enabled"] is False and acknowledged["configs"] == configs
    assert acknowledged["version"] == selected["version"] + 1
    ignored = {"schedule_enabled", "version", "updated_at", "configs"}
    assert {key: value for key, value in acknowledged.items() if key not in ignored} == {
        key: value for key, value in selected.items() if key not in ignored}
    assert get_job(other["id"]) == other and list_configs(selected["id"]) == configs
    repeated = client.patch(f"/api/jobs/{selected['id']}/scheduling", json={"schedule_enabled": False})
    assert repeated.json() == acknowledged


@pytest.mark.parametrize("body", [{}, {"schedule_enabled": None}, {"schedule_enabled": "false"},
    {"schedule_enabled": 0}, {"schedule_enabled": 1}, {"schedule_enabled": False, "expected_version": 1},
    {"schedule_enabled": False, "input_params": {"command": "echo changed"}}])
def test_scheduling_patch_rejects_coercion_and_extra_fields_without_writes(client, body):
    selected = job()
    configs = list_configs(selected["id"])
    assert client.patch(f"/api/jobs/{selected['id']}/scheduling", json=body).status_code == 422
    assert get_job(selected["id"]) == selected and list_configs(selected["id"]) == configs


@pytest.mark.parametrize("path,status", [("0", 422), ("-1", 422), ("invalid", 422), ("2147483647", 404)])
def test_scheduling_patch_validates_job_boundary(client, path, status):
    assert client.patch(f"/api/jobs/{path}/scheduling", json={"schedule_enabled": False}).status_code == status


@pytest.mark.parametrize("state", ["proposed", "rejected"])
def test_scheduling_patch_excludes_inactive_jobs(client, state):
    selected = job()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE background_jobs SET state=%s WHERE id=%s", (state, selected["id"]))
    before = get_job(selected["id"])
    assert client.patch(f"/api/jobs/{selected['id']}/scheduling", json={"schedule_enabled": False}).status_code == 404
    assert get_job(selected["id"]) == before


def test_scheduling_patch_presents_its_acknowledged_state_without_a_flag_reread(client, monkeypatch):
    selected = job()
    original = router_module.list_configs
    def change_after_acknowledgement(job_id):
        set_schedule_enabled(job_id, True)
        return original(job_id)
    monkeypatch.setattr(router_module, "list_configs", change_after_acknowledgement)
    response = client.patch(f"/api/jobs/{selected['id']}/scheduling", json={"schedule_enabled": False})
    assert response.status_code == 200 and response.json()["schedule_enabled"] is False
    assert response.json()["version"] == selected["version"] + 1
    assert get_job(selected["id"])["schedule_enabled"] is True


def test_pause_waits_for_automatic_admission_to_record_its_execution(monkeypatch):
    selected = job()
    admitted, insert_allowed, pause_entered = threading.Event(), threading.Event(), threading.Event()
    pids = {}
    original_create = BaseModel.create.__func__
    original_connection = job_model.get_connection
    def hold_admission(cls, conn=None, **fields):
        if cls is execution_model.JobExecutionModel:
            pids["admission"] = conn.get_backend_pid()
            admitted.set()
            assert insert_allowed.wait(timeout=3)
        return original_create(cls, conn=conn, **fields)
    @contextmanager
    def track_pause():
        with original_connection() as conn:
            pids["pause"] = conn.get_backend_pid()
            pause_entered.set()
            yield conn
    monkeypatch.setattr(BaseModel, "create", classmethod(hold_admission))
    monkeypatch.setattr(job_model, "get_connection", track_pause)
    with ThreadPoolExecutor(max_workers=2) as pool:
        admission = pool.submit(create_execution, selected["id"], automatic=True)
        try:
            assert admitted.wait(timeout=3)
            pause = pool.submit(set_schedule_enabled, selected["id"], False)
            assert pause_entered.wait(timeout=3)
            database_blocked_by(pids["pause"], pids["admission"])
            assert not pause.done()
        finally:
            insert_allowed.set()
        execution_id = admission.result(timeout=3)
        assert execution_id is not None and pause.result(timeout=3)["schedule_enabled"] is False
    assert get_execution(execution_id)["status"] == "running"
    assert create_execution(selected["id"], automatic=True) is None
    assert list_executions_for_job(selected["id"])[1] == 1


def test_automatic_admission_waits_for_pause_then_creates_no_execution(monkeypatch):
    selected = job()
    paused, commit_allowed, admission_entered = threading.Event(), threading.Event(), threading.Event()
    pids = {}
    original_pause_connection = job_model.get_connection
    original_execution_connection = execution_model.get_connection
    @contextmanager
    def hold_pause_commit():
        with original_pause_connection() as conn:
            pids["pause"] = conn.get_backend_pid()
            yield conn
            paused.set()
            assert commit_allowed.wait(timeout=3)
    @contextmanager
    def track_admission():
        with original_execution_connection() as conn:
            pids["admission"] = conn.get_backend_pid()
            admission_entered.set()
            yield conn
    monkeypatch.setattr(job_model, "get_connection", hold_pause_commit)
    monkeypatch.setattr(execution_model, "get_connection", track_admission)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pause = pool.submit(set_schedule_enabled, selected["id"], False)
        try:
            assert paused.wait(timeout=3)
            admission = pool.submit(create_execution, selected["id"], automatic=True)
            assert admission_entered.wait(timeout=3)
            database_blocked_by(pids["admission"], pids["pause"])
            assert not admission.done()
        finally:
            commit_allowed.set()
        assert pause.result(timeout=3)["schedule_enabled"] is False
        assert admission.result(timeout=3) is None
    assert list_executions_for_job(selected["id"])[1] == 0


@pytest.mark.asyncio
async def test_scheduler_skip_fences_a_stale_eligible_snapshot_and_keeps_other_job_normal(monkeypatch):
    selected, other = job(), job()
    scheduler = JobScheduler(device_name="scheduling-test")
    snapshot = scheduler._eligible_jobs()
    assert {selected["id"], other["id"]}.issubset({item["id"] for item in snapshot})
    set_schedule_enabled(selected["id"], False)
    assert selected["id"] not in {item["id"] for item in scheduler._eligible_jobs()}
    monkeypatch.setattr(scheduler, "_eligible_jobs", lambda: [selected, other])
    monkeypatch.setattr("services.jobs.service.has_requested_work", lambda row: True)
    scheduler._next_run = {row["id"]: datetime.now(timezone.utc) + timedelta(hours=1) for row in (selected, other)}
    await scheduler._tick()
    await asyncio.wait_for(asyncio.gather(*scheduler._inflight), timeout=3)
    assert list_executions_for_job(selected["id"])[1] == 0
    executions, total = list_executions_for_job(other["id"])
    assert total == 1 and executions[0]["status"] == "success"
    assert "scheduling-test" in executions[0]["result"]["output"]
    assert get_job(other["id"]) == other


@pytest.mark.asyncio
async def test_pausing_already_admitted_work_does_not_cancel_or_lock_external_execution(monkeypatch):
    selected = job()
    entered, finish = asyncio.Event(), asyncio.Event()
    original = scheduler_module._run_command_job
    async def waiting(*args, **kwargs):
        entered.set()
        await finish.wait()
        return await original(*args, **kwargs)
    monkeypatch.setattr(scheduler_module, "_run_command_job", waiting)
    task = asyncio.create_task(execute_job(selected, automatic=True))
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        assert list_executions_for_job(selected["id"])[0][0]["status"] == "running"
        paused = await asyncio.wait_for(asyncio.to_thread(set_schedule_enabled, selected["id"], False), timeout=3)
        assert paused["schedule_enabled"] is False and not task.done()
    finally:
        finish.set()
    result = await asyncio.wait_for(task, timeout=3)
    assert result["success"] and get_execution(result["execution_id"])["status"] == "success"
    assert (await execute_job(selected, automatic=True))["skipped"] is True
    assert list_executions_for_job(selected["id"])[1] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["rest", "mcp"])
async def test_paused_job_still_runs_manually_with_history(client, entrypoint):
    selected = job()
    set_schedule_enabled(selected["id"], False)
    configs = list_configs(selected["id"])
    if entrypoint == "rest":
        response = client.post(f"/api/jobs/{selected['id']}/run-now")
        assert response.status_code == 200
        result = response.json()
    else:
        result = await server.job_run_now(selected["id"])
    assert result["success"] and "scheduling-test" in result["output"]
    assert get_execution(result["execution_id"])["status"] == "success"
    assert get_job(selected["id"])["schedule_enabled"] is False and list_configs(selected["id"]) == configs


def test_auto_pause_does_not_remove_manual_meeting_analysis_worker_coverage(source, saved, payload, jobs):
    from services.meetings import digestion_db, manual_analysis, manual_stage

    meeting_id = saved()
    for graph in ("meeting_ingest", "persona"):
        set_schedule_enabled(jobs(graph)["id"], False)
    request = manual_analysis.request_analysis(payload(meeting_id, scope="both"))
    assert request["status"] == "queued"
    assert digestion_db.claim_manual_memory([(source.provider, source.account_key)], "manual-memory")
    assert manual_stage.before_analysis(meeting_id, "manual-memory", digestion_db.get_record(meeting_id)["transcript_hash"], "memory")["request_id"] == request["request_id"]
    digestion_db.release_owner("manual-memory")
    assert digestion_db.claim_profile(source.name, "manual-profile")
    assert manual_stage.before_analysis(meeting_id, "manual-profile", digestion_db.get_record(meeting_id)["transcript_hash"], "profile")["request_id"] == request["request_id"]
    digestion_db.release_profile_owner("manual-profile")
