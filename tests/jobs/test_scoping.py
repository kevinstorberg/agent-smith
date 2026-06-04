"""Device/repo scoping tests for background jobs (Tracer Bullet 3)."""
from __future__ import annotations

import asyncio

import pytest

from services.jobs.models.config import create_config
from services.jobs.models.execution import list_executions_for_job
from services.jobs.models.job import create_job
from services.jobs.scheduler import JobScheduler
from services.jobs.scoping import job_runs_on_device, resolve_job_targets
from tests.conftest import jobs_cleanup

_clean = jobs_cleanup("JOBTEST %")


def _job() -> int:
    return create_job(
        name="JOBTEST Scope",
        schedule_config={"minutes": 5},
        input_params={"command": "echo scope"},
    )


def test_no_config_means_no_targets():
    job_id = _job()
    assert resolve_job_targets(job_id, "laptop") == []
    assert job_runs_on_device(job_id, "laptop") is False


def test_wildcard_device_runs_everywhere():
    job_id = _job()
    create_config(job_id=job_id, device="*", repo="*", enabled=True)
    assert job_runs_on_device(job_id, "laptop") is True
    assert job_runs_on_device(job_id, "desktop") is True


def test_specific_device_only_matches_that_device():
    job_id = _job()
    create_config(job_id=job_id, device="laptop", repo="*", enabled=True)
    assert job_runs_on_device(job_id, "laptop") is True
    assert job_runs_on_device(job_id, "desktop") is False


def test_disabled_config_is_ignored():
    job_id = _job()
    create_config(job_id=job_id, device="*", repo="*", enabled=False)
    assert job_runs_on_device(job_id, "laptop") is False


def test_exclude_subtracts_repo():
    job_id = _job()
    create_config(job_id=job_id, device="*", repo="/work/a", enabled=True)
    create_config(job_id=job_id, device="*", repo="/work/b", enabled=True)
    create_config(job_id=job_id, device="*", repo="/work/b", enabled=True, exclude=True)

    targets = resolve_job_targets(job_id, "laptop")
    assert targets == ["/work/a"]


@pytest.mark.asyncio
async def test_scheduler_skips_job_scoped_to_other_device():
    job_id = create_job(
        name="JOBTEST Other Device",
        schedule_config={"seconds": 1},
        input_params={"command": "echo nope"},
    )
    create_config(job_id=job_id, device="other-device", repo="*", enabled=True)

    scheduler = JobScheduler(poll_interval=0.05, device_name="this-device")
    await scheduler.start()
    try:
        await asyncio.sleep(1.5)  # well past one interval
        _, total = list_executions_for_job(job_id, limit=5)
        assert total == 0, "job scoped to another device must not run here"
    finally:
        await scheduler.stop()
