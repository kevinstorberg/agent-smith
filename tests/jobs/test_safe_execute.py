import asyncio

import pytest

from src.jobs.base import BaseJob
from src.jobs.scheduler import JobScheduler


class FailingJob(BaseJob):
    name = "failing_job"

    async def execute(self):
        raise RuntimeError("intentional failure")


class SlowJob(BaseJob):
    name = "slow_job"
    timeout_seconds = 0.1

    async def execute(self):
        await asyncio.sleep(10)


class SuccessJob(BaseJob):
    name = "success_job"
    executed = False

    async def execute(self):
        SuccessJob.executed = True


@pytest.mark.unit
class TestSafeExecute:
    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self):
        scheduler = JobScheduler()
        job = FailingJob()
        await scheduler._safe_execute(job)

    @pytest.mark.asyncio
    async def test_timeout_does_not_propagate(self):
        scheduler = JobScheduler()
        job = SlowJob()
        await scheduler._safe_execute(job)

    @pytest.mark.asyncio
    async def test_successful_job_completes(self):
        scheduler = JobScheduler()
        job = SuccessJob()
        SuccessJob.executed = False
        await scheduler._safe_execute(job)
        assert SuccessJob.executed is True

    @pytest.mark.asyncio
    async def test_job_without_timeout_runs_normally(self):
        scheduler = JobScheduler()
        job = SuccessJob()
        SuccessJob.executed = False
        assert not hasattr(job, "timeout_seconds") or job.timeout_seconds is None
        await scheduler._safe_execute(job)
        assert SuccessJob.executed is True
