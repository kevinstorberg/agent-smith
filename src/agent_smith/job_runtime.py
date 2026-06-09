from __future__ import annotations

import asyncio
import logging
from typing import Any

from db.unit_of_work import unit_of_work
from src.agent_smith.repositories.jobs import JobExecutionRepository
from src.agent_smith.services.jobs import JobService, execute_job, job_runs_on_device
from src.agent_smith.validation import parse_interval, require_command
from src.jobs.base import BaseJob
from src.jobs.context import JobContext
from src.jobs.definitions import JobDefinition, LockPolicy, RetryPolicy, import_path_for
from src.jobs.runtime import JobRuntime
from src.settings import get_settings

logger = logging.getLogger(__name__)

AGENT_SMITH_JOB_NAMESPACE = "agent_smith"


def agent_smith_job_name(job_id: int) -> str:
    return f"{AGENT_SMITH_JOB_NAMESPACE}:{job_id}"


class AgentSmithCommandJob(BaseJob):
    name = "agent_smith_command"

    async def execute(self, context: JobContext) -> None:
        raw_job_id = context.metadata.get("agent_smith_job_id")
        if not isinstance(raw_job_id, int):
            raise ValueError("Agent Smith job metadata must include integer agent_smith_job_id")

        async with unit_of_work() as uow:
            job = await JobService().get_job(uow, raw_job_id, detail=True)
        if job is None:
            raise KeyError(f"Agent Smith job not found: {raw_job_id}")

        result = await execute_job(job)
        if result.get("success"):
            return

        error = str(result.get("error") or "Agent Smith command job failed")
        if error.startswith("timed out after"):
            raise asyncio.TimeoutError(error)
        raise RuntimeError(error)


def build_agent_smith_command_job() -> BaseJob:
    return AgentSmithCommandJob()


async def load_agent_smith_job_definitions(*, device_name: str | None = None) -> dict[str, JobDefinition]:
    settings = get_settings()
    device = device_name or settings.DEVICE_NAME
    definitions: dict[str, JobDefinition] = {}
    async with unit_of_work() as uow:
        jobs, _ = await JobService().list_jobs(uow, limit=1000, offset=0)
        for row in jobs:
            detail = await JobService().get_job(uow, row["id"], detail=True)
            if detail is None or not job_runs_on_device(detail, device):
                continue
            definition = _definition_for_agent_smith_job(detail, device_name=device)
            if definition is not None:
                definitions[definition.name] = definition
    return definitions


def _definition_for_agent_smith_job(job: dict[str, Any], *, device_name: str) -> JobDefinition | None:
    try:
        interval = parse_interval(job.get("schedule_config") or {})
        require_command(job.get("input_params") or {})
    except ValueError:
        logger.exception("Skipping invalid Agent Smith job", extra={"job_id": job.get("id")})
        return None

    timeout = float((job.get("input_params") or {}).get("timeout") or get_settings().JOB_DEFAULT_TIMEOUT)
    trigger_kwargs = {
        key: value
        for key, value in (job.get("schedule_config") or {}).items()
        if key in {"seconds", "minutes", "hours", "days"}
    }
    trigger_kwargs.update({"max_instances": 1, "coalesce": True})
    return JobDefinition(
        name=agent_smith_job_name(job["id"]),
        factory=import_path_for(build_agent_smith_command_job),
        trigger="interval",
        trigger_kwargs=trigger_kwargs,
        timeout_seconds=timeout + 1,
        retry_policy=RetryPolicy(max_attempts=1),
        lock_policy=LockPolicy(
            enabled=True,
            key=agent_smith_job_name(job["id"]),
            ttl_seconds=max(timeout + 60, interval.total_seconds() + 60),
        ),
        metadata={
            "agent_smith_job_id": job["id"],
            "agent_smith_job_name": job["name"],
            "device": device_name,
        },
    )


class AgentSmithJobRuntimeAdapter:
    def __init__(
        self,
        runtime: JobRuntime,
        *,
        poll_interval: float | None = None,
        device_name: str | None = None,
    ) -> None:
        settings = get_settings()
        self.runtime = runtime
        self.poll_interval = float(poll_interval if poll_interval is not None else settings.JOB_POLL_INTERVAL)
        self.device_name = device_name or settings.DEVICE_NAME
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self._stopped.clear()
        async with unit_of_work() as uow:
            interrupted = await JobExecutionRepository(uow.session).reconcile_running(device=self.device_name)
        if interrupted:
            logger.warning("Reconciled Agent Smith execution(s) left running", extra={"count": interrupted})
        await self.refresh()
        self._task = asyncio.create_task(self._run(), name="agent-smith-job-runtime-refresh")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def refresh(self) -> None:
        definitions = await load_agent_smith_job_definitions(device_name=self.device_name)
        self.runtime.sync_namespace(AGENT_SMITH_JOB_NAMESPACE, definitions)

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                await self.refresh()
