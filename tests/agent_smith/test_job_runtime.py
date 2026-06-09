from __future__ import annotations

import asyncio
import sys

import pytest

from config.models import DefaultConfig, JobsConfig
from db.models.agent_smith import JobExecution
from db.unit_of_work import unit_of_work
from src.agent_smith.job_runtime import (
    AgentSmithJobRuntimeAdapter,
    agent_smith_job_name,
    load_agent_smith_job_definitions,
)
from src.agent_smith.repositories.jobs import JobExecutionRepository
from src.agent_smith.services.jobs import JobService
from src.jobs.runtime import create_job_runtime
from src.jobs.stores import JobRunStatus
from src.settings import Settings, get_settings


def _command(source: str) -> str:
    return f"{sys.executable} -c {source!r}"


async def _create_job(
    *,
    command: str,
    schedule_config: dict | None = None,
    timeout: float = 5,
    name: str = "port_job",
) -> dict:
    async with unit_of_work() as uow:
        return await JobService().create_job(
            uow,
            name=name,
            description="Regression job",
            schedule_config=schedule_config or {"seconds": 60},
            input_params={"command": command, "timeout": timeout},
        )


async def _execution_statuses(job_id: int) -> list[str]:
    async with unit_of_work() as uow:
        rows, _ = await JobExecutionRepository(uow.session).list_for_job(job_id, limit=20, offset=0)
    return [row["status"] for row in rows]


@pytest.mark.asyncio
async def test_agent_smith_job_definitions_run_through_agent_smith_runtime(clean_agent_smith_db):
    job = await _create_job(command=_command("print('agent smith job ok')"))
    definitions = await load_agent_smith_job_definitions()
    runtime = create_job_runtime(
        DefaultConfig(jobs=JobsConfig(auto_discover=False)),
        Settings(_env_file=None),
    )
    runtime.sync_namespace("agent_smith", definitions)

    record = await runtime.run_job(agent_smith_job_name(job["id"]))

    assert record.status == JobRunStatus.SUCCESS
    assert await _execution_statuses(job["id"]) == ["success"]
    assert runtime.list_jobs()[0]["metadata"]["agent_smith_job_id"] == job["id"]


@pytest.mark.asyncio
async def test_agent_smith_job_adapter_marks_command_failures_and_timeouts(clean_agent_smith_db):
    failed = await _create_job(command=_command("import sys; sys.stderr.write('bad'); sys.exit(3)"), name="failed_job")
    timed_out = await _create_job(command=_command("import time; time.sleep(2)"), timeout=0.1, name="timeout_job")
    definitions = await load_agent_smith_job_definitions()
    runtime = create_job_runtime(
        DefaultConfig(jobs=JobsConfig(auto_discover=False)),
        Settings(_env_file=None),
    )
    runtime.sync_namespace("agent_smith", definitions)

    failed_record = await runtime.run_job(agent_smith_job_name(failed["id"]))
    timeout_record = await runtime.run_job(agent_smith_job_name(timed_out["id"]))

    assert failed_record.status == JobRunStatus.FAILED
    assert timeout_record.status == JobRunStatus.TIMED_OUT
    assert await _execution_statuses(failed["id"]) == ["failed"]
    assert await _execution_statuses(timed_out["id"]) == ["timeout"]


@pytest.mark.asyncio
async def test_agent_smith_dynamic_definitions_respect_excluded_configs(clean_agent_smith_db):
    job = await _create_job(command=_command("print('excluded')"))
    async with unit_of_work() as uow:
        await JobService().create_config(
            uow,
            job["id"],
            device=get_settings().DEVICE_NAME,
            repo="*",
            enabled=True,
            exclude=True,
        )

    definitions = await load_agent_smith_job_definitions()

    assert agent_smith_job_name(job["id"]) not in definitions


@pytest.mark.asyncio
async def test_agent_smith_job_adapter_schedules_jobs_and_reconciles_running(clean_agent_smith_db):
    job = await _create_job(command=_command("print('scheduled')"), schedule_config={"seconds": 0.05})
    async with unit_of_work() as uow:
        uow.session.add(JobExecution(job_id=job["id"], status="running", device=get_settings().DEVICE_NAME))

    runtime = create_job_runtime(
        DefaultConfig(jobs=JobsConfig(auto_discover=False)),
        Settings(_env_file=None),
    )
    await runtime.start()
    adapter = AgentSmithJobRuntimeAdapter(runtime, poll_interval=0.05)
    await adapter.start()
    try:
        for _ in range(30):
            statuses = await _execution_statuses(job["id"])
            if "success" in statuses:
                break
            await asyncio.sleep(0.05)
        runtime.sync_namespace("agent_smith", {})
    finally:
        await adapter.stop()
        await runtime.shutdown()

    statuses = await _execution_statuses(job["id"])
    assert "interrupted" in statuses
    assert "success" in statuses
