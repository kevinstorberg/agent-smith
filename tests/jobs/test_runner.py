import asyncio

import pytest

from config.models import DefaultConfig
from db.unit_of_work import UnitOfWorkFactory
from src.jobs.base import BaseJob
from src.jobs.context import JobContext
from src.jobs.definitions import JobDefinition, RetryPolicy, import_path_for
from src.jobs.locks import InMemoryJobLockBackend
from src.jobs.runner import JobRunner
from src.jobs.stores import InMemoryJobStatusStore, JobRunStatus
from src.settings import Settings


class RunnerSuccessJob(BaseJob):
    name = "runner_success"
    calls = 0

    async def execute(self):
        RunnerSuccessJob.calls += 1


class RunnerContextJob(BaseJob):
    name = "runner_context"
    saw_context = False

    async def execute(self, context):
        RunnerContextJob.saw_context = isinstance(context, JobContext)


class RunnerFailThenPassJob(BaseJob):
    name = "runner_fail_then_pass"
    calls = 0

    async def execute(self):
        RunnerFailThenPassJob.calls += 1
        if RunnerFailThenPassJob.calls == 1:
            raise RuntimeError("try again")


class RunnerAlwaysFailsJob(BaseJob):
    name = "runner_always_fails"

    async def execute(self):
        raise RuntimeError("intentional failure")


class RunnerSlowJob(BaseJob):
    name = "runner_slow"

    async def execute(self):
        await asyncio.sleep(1)


def build_runner_success_job() -> BaseJob:
    return RunnerSuccessJob()


def build_runner_context_job() -> BaseJob:
    return RunnerContextJob()


def build_runner_fail_then_pass_job() -> BaseJob:
    return RunnerFailThenPassJob()


def build_runner_always_fails_job() -> BaseJob:
    return RunnerAlwaysFailsJob()


def build_runner_slow_job() -> BaseJob:
    return RunnerSlowJob()


def _runner(lock_backend=None):
    store = InMemoryJobStatusStore()
    runner = JobRunner(
        context=JobContext(
            config=DefaultConfig(),
            settings=Settings(_env_file=None),
            unit_of_work_factory=UnitOfWorkFactory(),
        ),
        status_store=store,
        lock_backend=lock_backend or InMemoryJobLockBackend(),
    )
    return runner, store


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_records_success_for_no_arg_job():
    runner, store = _runner()
    RunnerSuccessJob.calls = 0
    definition = JobDefinition(name="runner_success", factory=import_path_for(build_runner_success_job))

    record = await runner.run(definition)

    assert record.status == JobRunStatus.SUCCESS
    assert RunnerSuccessJob.calls == 1
    assert (await store.list_runs())[0].status == JobRunStatus.SUCCESS


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_passes_context_to_context_aware_job():
    runner, _store = _runner()
    RunnerContextJob.saw_context = False
    definition = JobDefinition(name="runner_context", factory=import_path_for(build_runner_context_job))

    await runner.run(definition)

    assert RunnerContextJob.saw_context is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_retries_and_records_successful_second_attempt():
    runner, store = _runner()
    RunnerFailThenPassJob.calls = 0
    definition = JobDefinition(
        name="runner_retry",
        factory=import_path_for(build_runner_fail_then_pass_job),
        retry_policy=RetryPolicy(max_attempts=2),
    )

    record = await runner.run(definition)
    runs = await store.list_runs()

    assert record.status == JobRunStatus.SUCCESS
    assert [run.status for run in runs] == [JobRunStatus.SUCCESS, JobRunStatus.FAILED]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_records_failure_after_retry_exhaustion():
    runner, _store = _runner()
    definition = JobDefinition(
        name="runner_fail",
        factory=import_path_for(build_runner_always_fails_job),
        retry_policy=RetryPolicy(max_attempts=2),
    )

    record = await runner.run(definition)

    assert record.status == JobRunStatus.FAILED
    assert record.attempt == 2
    assert record.error == "intentional failure"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_records_timeout():
    runner, _store = _runner()
    definition = JobDefinition(
        name="runner_slow",
        factory=import_path_for(build_runner_slow_job),
        timeout_seconds=0.01,
    )

    record = await runner.run(definition)

    assert record.status == JobRunStatus.TIMED_OUT


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_skips_when_lock_is_held():
    lock_backend = InMemoryJobLockBackend()
    lease = await lock_backend.acquire("job:runner_success", ttl_seconds=60)
    runner, _store = _runner(lock_backend)
    definition = JobDefinition(name="runner_success", factory=import_path_for(build_runner_success_job))

    try:
        record = await runner.run(definition)
    finally:
        await lease.release()

    assert record.status == JobRunStatus.SKIPPED_LOCK


@pytest.mark.unit
@pytest.mark.asyncio
async def test_runner_records_disabled_job():
    runner, _store = _runner()
    definition = JobDefinition(
        name="runner_disabled",
        factory=import_path_for(build_runner_success_job),
        enabled=False,
    )

    record = await runner.run(definition)

    assert record.status == JobRunStatus.DISABLED
