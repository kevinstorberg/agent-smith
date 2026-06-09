from __future__ import annotations

import asyncio
import logging
import os
import signal
import time

from db.models.agent_smith import BackgroundJob, JobConfig
from db.unit_of_work import UnitOfWork, unit_of_work
from src.agent_smith.repositories.jobs import JobConfigRepository, JobExecutionRepository, JobRepository
from src.agent_smith.serialization import model_to_dict
from src.agent_smith.validation import parse_interval, require_command
from src.services.application import ApplicationService
from src.settings import get_settings

log = logging.getLogger(__name__)


class JobService(ApplicationService):
    async def list_jobs(self, uow: UnitOfWork, *, limit: int, offset: int):
        return await JobRepository(uow.session).list_page(limit=limit, offset=offset)

    async def get_job(self, uow: UnitOfWork, job_id: int, *, detail: bool = False) -> dict | None:
        repo = JobRepository(uow.session)
        if detail:
            return await repo.get_detail(job_id)
        job = await repo.get(job_id)
        return model_to_dict(job) if job else None

    async def create_job(
        self, uow: UnitOfWork, *, name: str, schedule_config: dict, input_params: dict, description=None
    ):
        parse_interval(schedule_config)
        require_command(input_params)
        job = BackgroundJob(
            name=name,
            description=description,
            schedule_config=schedule_config,
            input_params=input_params,
        )
        JobRepository(uow.session).add(job)
        await uow.session.flush()
        JobConfigRepository(uow.session).add(
            JobConfig(job_id=job.id, device="*", repo="*", enabled=True, exclude=False)
        )
        await uow.session.flush()
        return await JobRepository(uow.session).get_detail(job.id)

    async def update_job(self, uow: UnitOfWork, job_id: int, **fields) -> dict | None:
        job = await JobRepository(uow.session).get(job_id)
        if job is None:
            return None
        if fields.get("schedule_config") is not None:
            parse_interval(fields["schedule_config"])
        if fields.get("input_params") is not None:
            require_command(fields["input_params"])
        for key, value in fields.items():
            if value is not None:
                setattr(job, key, value)
        return await JobRepository(uow.session).get_detail(job_id)

    async def delete_job(self, uow: UnitOfWork, job_id: int) -> bool:
        return await JobRepository(uow.session).delete_by_id(job_id)

    async def list_configs(self, uow: UnitOfWork, job_id: int) -> list[dict]:
        return await JobConfigRepository(uow.session).list_for_job(job_id)

    async def create_config(self, uow: UnitOfWork, job_id: int, **fields) -> list[dict]:
        JobConfigRepository(uow.session).add(JobConfig(job_id=job_id, **fields))
        await uow.session.flush()
        return await self.list_configs(uow, job_id)

    async def get_config(self, uow: UnitOfWork, config_id: int) -> dict | None:
        config = await JobConfigRepository(uow.session).get(config_id)
        return model_to_dict(config) if config else None

    async def update_config(self, uow: UnitOfWork, config_id: int, **fields) -> None:
        config = await JobConfigRepository(uow.session).get(config_id)
        if config is None:
            raise KeyError(f"Config not found: {config_id}")
        for key, value in fields.items():
            if value is not None:
                setattr(config, key, value)

    async def delete_config(self, uow: UnitOfWork, config_id: int) -> None:
        config = await JobConfigRepository(uow.session).get(config_id)
        if config is not None:
            await JobConfigRepository(uow.session).delete(config)

    async def list_executions(self, uow: UnitOfWork, job_id: int, *, limit: int, offset: int):
        return await JobExecutionRepository(uow.session).list_for_job(job_id, limit=limit, offset=offset)

    async def get_execution(self, uow: UnitOfWork, execution_id: int) -> dict | None:
        execution = await JobExecutionRepository(uow.session).get(execution_id)
        return model_to_dict(execution) if execution else None

    async def run_now(self, job: dict) -> dict:
        return await execute_job(job)


def job_runs_on_device(job: dict, device_name: str) -> bool:
    configs = job.get("configs", [])
    relevant = [config for config in configs if _device_matches(config["device"], device_name)]
    if not relevant:
        return False
    if any(config["exclude"] for config in relevant):
        return False
    return any(config["enabled"] for config in relevant)


def _device_matches(config_device: str, device_name: str) -> bool:
    if config_device == "*":
        return True
    return bool(device_name) and config_device == device_name


def _truncate(data: bytes, limit: int) -> str:
    text = data.decode("utf-8", errors="replace")
    if len(text) > limit:
        return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"
    return text


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def _create_execution(job_id: int, device: str) -> int:
    async with unit_of_work() as uow:
        return await JobExecutionRepository(uow.session).create_running(job_id=job_id, device=device)


async def _complete_execution(execution_id: int, *, status: str, result: dict) -> None:
    async with unit_of_work() as uow:
        await JobExecutionRepository(uow.session).complete(execution_id, status=status, result=result)


async def execute_job(job: dict) -> dict:
    settings = get_settings()
    job_id = job["id"]
    params = job.get("input_params") or {}
    command = params.get("command")
    execution_id = await _create_execution(job_id, settings.DEVICE_NAME)

    if not command:
        result = {
            "success": False,
            "output": "",
            "error": "input_params.command is required",
            "duration_seconds": 0.0,
            "exit_code": None,
        }
        await _complete_execution(execution_id, status="failed", result=result)
        return result

    start = time.monotonic()
    proc: asyncio.subprocess.Process | None = None
    try:
        timeout = float(params.get("timeout", settings.JOB_DEFAULT_TIMEOUT))
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            _kill_process_group(proc)
            await proc.wait()
            result = {
                "success": False,
                "output": "",
                "error": f"timed out after {timeout}s",
                "duration_seconds": round(time.monotonic() - start, 3),
                "exit_code": None,
            }
            await _complete_execution(execution_id, status="timeout", result=result)
            return result

        result = {
            "success": proc.returncode == 0,
            "output": _truncate(stdout, settings.JOB_MAX_OUTPUT_BYTES),
            "error": _truncate(stderr, settings.JOB_MAX_OUTPUT_BYTES),
            "duration_seconds": round(time.monotonic() - start, 3),
            "exit_code": proc.returncode,
        }
        await _complete_execution(execution_id, status="success" if proc.returncode == 0 else "failed", result=result)
        return result
    except asyncio.CancelledError:
        if proc is not None:
            _kill_process_group(proc)
        result = {
            "success": False,
            "output": "",
            "error": "cancelled (scheduler shutdown)",
            "duration_seconds": round(time.monotonic() - start, 3),
            "exit_code": None,
        }
        await _complete_execution(execution_id, status="interrupted", result=result)
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("job %s execution raised", job_id)
        result = {
            "success": False,
            "output": "",
            "error": f"{type(exc).__name__}: {exc}",
            "duration_seconds": round(time.monotonic() - start, 3),
            "exit_code": None,
        }
        await _complete_execution(execution_id, status="failed", result=result)
        return result
