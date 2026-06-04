"""Runtime tests for the background job scheduler engine (Tracer Bullet 2)."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from services.jobs.models.config import create_config
from services.jobs.models.execution import list_executions_for_job
from services.jobs.models.job import create_job
from services.jobs.schedule import parse_interval
from services.jobs.scheduler import JobScheduler, execute_job
from tests.conftest import jobs_cleanup

_clean = jobs_cleanup("JOBTEST %")


def test_parse_interval_valid():
    assert parse_interval({"minutes": 5}) == timedelta(minutes=5)
    assert parse_interval({"hours": 2, "seconds": 30}) == timedelta(hours=2, seconds=30)


@pytest.mark.parametrize(
    "bad",
    [{}, {"weeks": 1}, {"minutes": 0}, {"minutes": -1}, {"minutes": "x"}, {"minutes": True}],
)
def test_parse_interval_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_interval(bad)


def test_create_job_rejects_invalid_interval_keys():
    """create_job validates interval shape, not just non-emptiness."""
    with pytest.raises(ValueError):
        create_job(
            name="JOBTEST Bad Interval",
            schedule_config={"weeks": 2},
            input_params={"command": "echo nope"},
        )


@pytest.mark.asyncio
async def test_execute_job_records_success():
    job_id = create_job(
        name="JOBTEST Execute Success",
        schedule_config={"minutes": 5},
        input_params={"command": "echo hello-exec"},
    )

    result = await execute_job({"id": job_id, "input_params": {"command": "echo hello-exec"}})

    assert result["success"] is True
    assert result["exit_code"] == 0
    assert "hello-exec" in result["output"]

    items, total = list_executions_for_job(job_id, limit=5)
    assert total == 1
    assert items[0]["status"] == "success"
    assert items[0]["completed_at"] is not None


@pytest.mark.asyncio
async def test_execute_job_records_failure():
    job_id = create_job(
        name="JOBTEST Execute Failure",
        schedule_config={"minutes": 5},
        input_params={"command": "exit 3"},
    )

    result = await execute_job({"id": job_id, "input_params": {"command": "exit 3"}})

    assert result["success"] is False
    assert result["exit_code"] == 3

    items, _ = list_executions_for_job(job_id, limit=5)
    assert items[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_execute_job_missing_command_is_failure():
    job_id = create_job(
        name="JOBTEST Execute NoCommand",
        schedule_config={"minutes": 5},
        input_params={"command": "echo placeholder"},
    )

    result = await execute_job({"id": job_id, "input_params": {}})

    assert result["success"] is False
    items, _ = list_executions_for_job(job_id, limit=5)
    assert items[0]["status"] == "failed"


def test_reconcile_marks_running_executions_interrupted():
    from services.jobs.models.execution import (
        create_execution,
        get_execution,
        reconcile_running_executions,
    )

    job_id = create_job(
        name="JOBTEST Reconcile",
        schedule_config={"minutes": 5},
        input_params={"command": "echo x"},
    )
    exec_id = create_execution(job_id=job_id, status="running")

    reconcile_running_executions()

    execution = get_execution(exec_id)
    assert execution["status"] == "interrupted"
    assert execution["completed_at"] is not None


@pytest.mark.asyncio
async def test_scheduler_fires_interval_job_and_records_execution():
    """The core TB2 assumption: an interval job actually fires async in the loop."""
    job_id = create_job(
        name="JOBTEST Scheduler Fire",
        schedule_config={"seconds": 1},
        input_params={"command": "echo fired"},
    )
    create_config(job_id=job_id, device="*", repo="*", enabled=True)

    scheduler = JobScheduler(poll_interval=0.05)
    await scheduler.start()
    try:
        found = None
        for _ in range(120):  # poll up to ~6s
            await asyncio.sleep(0.05)
            items, _ = list_executions_for_job(job_id, limit=5)
            done = [e for e in items if e["status"] in ("success", "failed", "timeout")]
            if done:
                found = done[0]
                break
        assert found is not None, "scheduler never recorded a completed execution"
        assert found["status"] == "success"
        assert "fired" in found["result"]["output"]
    finally:
        await scheduler.stop()
