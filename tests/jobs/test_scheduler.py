import asyncio

import pytest

from src.jobs.base import BaseJob
from src.jobs.scheduler import JobScheduler


class MockJob(BaseJob):
    name = "mock_job"
    call_count = 0

    async def execute(self):
        MockJob.call_count += 1


class ScheduledJob(BaseJob):
    name = "scheduled_job"
    timeout_seconds = 1

    def __init__(self, fired: asyncio.Event):
        self.fired = fired
        self.call_count = 0

    async def execute(self):
        self.call_count += 1
        self.fired.set()


@pytest.mark.unit
class TestBaseJob:
    def test_base_job_has_name(self):
        job = MockJob()
        assert job.name == "mock_job"

    def test_base_job_has_execute(self):
        job = MockJob()
        assert hasattr(job, "execute")
        assert callable(job.execute)


@pytest.mark.unit
class TestJobScheduler:
    def test_scheduler_instantiates(self):
        scheduler = JobScheduler()
        assert scheduler is not None

    def test_register_job(self):
        scheduler = JobScheduler()
        job = MockJob()
        scheduler.register(job, trigger="interval", seconds=60)
        assert len(scheduler.registered_jobs) == 1

    def test_register_multiple_jobs(self):
        scheduler = JobScheduler()
        job1 = MockJob()
        job2 = MockJob()
        scheduler.register(job1, trigger="interval", seconds=60)
        scheduler.register(job2, trigger="interval", seconds=120)
        assert len(scheduler.registered_jobs) == 2

    @pytest.mark.asyncio
    async def test_start_runs_registered_interval_job(self):
        scheduler = JobScheduler()
        fired = asyncio.Event()
        job = ScheduledJob(fired)

        scheduler.register(
            job,
            trigger="interval",
            seconds=0.05,
            max_instances=1,
            coalesce=True,
        )

        await scheduler.start()
        try:
            await asyncio.wait_for(fired.wait(), timeout=1)
        finally:
            await scheduler.shutdown()

        assert job.call_count >= 1
