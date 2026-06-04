"""Background job scheduler: a pure-asyncio interval loop + subprocess executor.

The scheduler is a single long-lived asyncio task started from the FastAPI
lifespan. Because it is created with ``asyncio.create_task`` inside the running
uvicorn event loop, the job coroutine always runs in a context that has a
current event loop — this avoids the APScheduler "no current event loop in
worker thread" trap by construction.

V1 scope: interval scheduling only, one script per job (``input_params.command``),
no retry. Device/repo config scoping (job_configs) is layered on in TB3 — for now
every job in the table is eligible.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from services.config import (
    DEVICE_NAME,
    JOB_DEFAULT_TIMEOUT,
    JOB_MAX_OUTPUT_BYTES,
    JOB_POLL_INTERVAL,
)
from services.jobs.models.execution import (
    complete_execution,
    create_execution,
    reconcile_running_executions,
)
from services.jobs.models.job import list_jobs
from services.jobs.schedule import parse_interval
from services.jobs.scoping import job_runs_on_device

log = logging.getLogger("jobs.scheduler")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _truncate(data: bytes, limit: int) -> str:
    text = data.decode("utf-8", errors="replace")
    if len(text) > limit:
        return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"
    return text


async def execute_job(job: dict) -> dict:
    """Run a job's script once, recording a ``job_executions`` row.

    Never raises: a failing script is recorded as a failed/timeout execution so
    a bad job can never crash the scheduler loop. Returns the result dict.
    """
    job_id = job["id"]
    params = job.get("input_params") or {}
    command = params.get("command")
    timeout = float(params.get("timeout", JOB_DEFAULT_TIMEOUT))
    exec_id = create_execution(job_id=job_id, status="running")

    if not command:
        result = {
            "success": False,
            "output": "",
            "error": "input_params.command is required",
            "duration_seconds": 0.0,
            "exit_code": None,
        }
        complete_execution(exec_id, status="failed", result=result)
        return result

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            result = {
                "success": False,
                "output": "",
                "error": f"timed out after {timeout}s",
                "duration_seconds": round(time.monotonic() - start, 3),
                "exit_code": None,
            }
            complete_execution(exec_id, status="timeout", result=result)
            return result

        exit_code = proc.returncode
        result = {
            "success": exit_code == 0,
            "output": _truncate(stdout, JOB_MAX_OUTPUT_BYTES),
            "error": _truncate(stderr, JOB_MAX_OUTPUT_BYTES),
            "duration_seconds": round(time.monotonic() - start, 3),
            "exit_code": exit_code,
        }
        complete_execution(
            exec_id, status="success" if exit_code == 0 else "failed", result=result
        )
        return result
    except Exception as exc:  # noqa: BLE001 - job failures must not crash the scheduler
        log.exception("job %s execution raised", job_id)
        result = {
            "success": False,
            "output": "",
            "error": f"{type(exc).__name__}: {exc}",
            "duration_seconds": round(time.monotonic() - start, 3),
            "exit_code": None,
        }
        complete_execution(exec_id, status="failed", result=result)
        return result


class JobScheduler:
    """Polls for due interval jobs and executes them in the event loop."""

    def __init__(
        self, poll_interval: float | None = None, device_name: str | None = None
    ) -> None:
        self.poll_interval = float(
            poll_interval if poll_interval is not None else JOB_POLL_INTERVAL
        )
        self.device_name = device_name if device_name is not None else DEVICE_NAME
        self._next_run: dict[int, datetime] = {}
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self._stopped.clear()
        interrupted = reconcile_running_executions()
        if interrupted:
            log.warning("reconciled %d execution(s) left running at startup", interrupted)
        self._seed_schedule()
        self._task = asyncio.create_task(self._run(), name="job-scheduler")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task:
            await self._task
            self._task = None

    def _eligible_jobs(self) -> list[dict]:
        # Only jobs whose job_configs scope them to this device are eligible.
        jobs, _ = list_jobs(limit=1000, offset=0)
        return [j for j in jobs if job_runs_on_device(j["id"], self.device_name)]

    def _seed_schedule(self) -> None:
        now = _utcnow()
        for job in self._eligible_jobs():
            try:
                interval = parse_interval(job["schedule_config"])
            except ValueError:
                log.error(
                    "skipping job %s: invalid schedule_config %r",
                    job.get("id"),
                    job.get("schedule_config"),
                )
                continue
            self._next_run[job["id"]] = now + interval

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                await self._tick()
            except Exception:  # noqa: BLE001 - one bad tick must not kill the loop
                log.exception("scheduler tick failed")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        now = _utcnow()
        for job in self._eligible_jobs():
            job_id = job["id"]
            try:
                interval = parse_interval(job["schedule_config"])
            except ValueError:
                continue
            next_run = self._next_run.get(job_id)
            if next_run is None:
                self._next_run[job_id] = now + interval
                continue
            if next_run <= now:
                self._next_run[job_id] = now + interval
                await execute_job(job)
