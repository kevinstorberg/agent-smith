"""Background job scheduler: a pure-asyncio interval loop + subprocess executor.

The scheduler is a single long-lived asyncio task started from the FastAPI
lifespan. Because it is created with ``asyncio.create_task`` inside the running
uvicorn event loop, the job coroutine always runs in a context that has a
current event loop — this avoids the APScheduler "no current event loop in
worker thread" trap by construction.

Each due job is dispatched as its own task, so a slow job never blocks the poll
loop or other jobs, and a job already in flight is skipped rather than run
concurrently with itself. Blocking psycopg2 calls are pushed off the event loop
with ``asyncio.to_thread``.

V1 scope: interval scheduling only, one shell command per job
(``input_params.command``), no retry. Jobs are gated by their job_configs
device/repo scoping (see ``services.jobs.scoping``).
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
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


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL the whole process group of a subprocess started with
    ``start_new_session=True``, so commands that fork children don't leak."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def execute_job(job: dict) -> dict:
    """Run a job's script once, recording a ``job_executions`` row.

    Never raises for a bad command/timeout/error — those are recorded as a
    failed/timeout execution so the scheduler loop is never crashed. Cancellation
    (scheduler shutdown) is recorded as 'interrupted' and re-raised after killing
    the subprocess. Returns the result dict.
    """
    job_id = job["id"]
    params = job.get("input_params") or {}
    command = params.get("command")
    exec_id = await asyncio.to_thread(create_execution, job_id=job_id, status="running")

    if not command:
        result = {
            "success": False,
            "output": "",
            "error": "input_params.command is required",
            "duration_seconds": 0.0,
            "exit_code": None,
        }
        await asyncio.to_thread(complete_execution, exec_id, status="failed", result=result)
        return result

    start = time.monotonic()
    proc: asyncio.subprocess.Process | None = None
    try:
        timeout = float(params.get("timeout", JOB_DEFAULT_TIMEOUT))
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
            await asyncio.to_thread(complete_execution, exec_id, status="timeout", result=result)
            return result

        exit_code = proc.returncode
        result = {
            "success": exit_code == 0,
            "output": _truncate(stdout, JOB_MAX_OUTPUT_BYTES),
            "error": _truncate(stderr, JOB_MAX_OUTPUT_BYTES),
            "duration_seconds": round(time.monotonic() - start, 3),
            "exit_code": exit_code,
        }
        await asyncio.to_thread(
            complete_execution, exec_id, status="success" if exit_code == 0 else "failed", result=result
        )
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
        # Synchronous so the row is finalized before the cancellation propagates.
        complete_execution(exec_id, status="interrupted", result=result)
        raise
    except Exception as exc:  # noqa: BLE001 - job failures must not crash the scheduler
        log.exception("job %s execution raised", job_id)
        result = {
            "success": False,
            "output": "",
            "error": f"{type(exc).__name__}: {exc}",
            "duration_seconds": round(time.monotonic() - start, 3),
            "exit_code": None,
        }
        await asyncio.to_thread(complete_execution, exec_id, status="failed", result=result)
        return result


class JobScheduler:
    """Polls for due interval jobs and dispatches each as its own task."""

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
        self._running: set[int] = set()        # job ids currently executing (overlap guard)
        self._inflight: set[asyncio.Task] = set()  # in-flight execution tasks

    async def start(self) -> None:
        self._stopped.clear()
        interrupted = await asyncio.to_thread(reconcile_running_executions, self.device_name)
        if interrupted:
            log.warning("reconciled %d execution(s) left running at startup", interrupted)
        await self._seed_schedule()
        self._task = asyncio.create_task(self._run(), name="job-scheduler")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task:
            await self._task
            self._task = None
        # Cancel any in-flight job executions so shutdown is prompt; each kills
        # its own subprocess group and records an 'interrupted' execution.
        for task in list(self._inflight):
            task.cancel()
        if self._inflight:
            await asyncio.gather(*self._inflight, return_exceptions=True)

    def _eligible_jobs(self) -> list[dict]:
        # Only jobs whose job_configs scope them to this device are eligible.
        jobs, _ = list_jobs(limit=1000, offset=0)
        return [j for j in jobs if job_runs_on_device(j["id"], self.device_name)]

    async def _seed_schedule(self) -> None:
        now = _utcnow()
        for job in await asyncio.to_thread(self._eligible_jobs):
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

    def _dispatch(self, job: dict) -> None:
        job_id = job["id"]
        if job_id in self._running:
            log.warning("job %s still running; skipping this interval", job_id)
            return
        self._running.add(job_id)
        task = asyncio.create_task(execute_job(job), name=f"job-{job_id}")
        self._inflight.add(task)

        def _done(t: asyncio.Task) -> None:
            self._inflight.discard(t)
            self._running.discard(job_id)

        task.add_done_callback(_done)

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
        for job in await asyncio.to_thread(self._eligible_jobs):
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
                self._dispatch(job)
