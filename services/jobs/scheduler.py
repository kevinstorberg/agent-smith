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

Scope: interval scheduling only, no retry. A job runs exactly one of a shell
command (``input_params.command``) or an in-process LangGraph workflow
(``input_params.graph_type`` + ``graph_inputs``). Jobs are gated by their
job_configs device/repo scoping (see ``services.jobs.scoping``).
"""
from __future__ import annotations

import asyncio
import contextlib
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


async def _pump(stream: asyncio.StreamReader | None, buf: bytearray) -> None:
    """Accumulate a stream into ``buf`` as it arrives, so output captured so far
    survives a kill — unlike communicate(), which discards partial reads on cancel."""
    if stream is None:
        return
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            return
        buf.extend(chunk)


async def execute_job(job: dict) -> dict:
    """Run a job once, recording a ``job_executions`` row.

    A job is either a shell command or an in-process graph run (see module
    docstring). Never raises for a bad definition/timeout/error — those are
    recorded as a failed/timeout execution so the scheduler loop is never
    crashed. Cancellation (scheduler shutdown) is recorded as 'interrupted'
    and re-raised. Returns the result dict.
    """
    job_id = job["id"]
    params = job.get("input_params") or {}
    command = params.get("command")
    graph_type = params.get("graph_type")
    exec_id = await asyncio.to_thread(create_execution, job_id=job_id, status="running")

    # Defense in depth for rows created before validate_input_params existed.
    if bool(command) == bool(graph_type):
        result = {
            "success": False,
            "output": "",
            "error": "input_params requires exactly one of 'command' or 'graph_type'",
            "duration_seconds": 0.0,
            "exit_code": None,
        }
        await asyncio.to_thread(complete_execution, exec_id, status="failed", result=result)
        return result

    if command:
        return await _run_command_job(exec_id, job_id, command, params)
    return await _run_graph_job(exec_id, job_id, graph_type, params)


async def _run_command_job(exec_id: int, job_id: int, command: str, params: dict) -> dict:
    start = time.monotonic()
    proc: asyncio.subprocess.Process | None = None
    out_buf, err_buf = bytearray(), bytearray()
    try:
        timeout = float(params.get("timeout", JOB_DEFAULT_TIMEOUT))
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        pumps = asyncio.gather(_pump(proc.stdout, out_buf), _pump(proc.stderr, err_buf))
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
            await pumps
        except asyncio.TimeoutError:
            _kill_process_group(proc)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(pumps, timeout=5)
            error = f"timed out after {timeout}s"
            if err_buf.strip():
                error += "\n--- partial stderr ---\n" + _truncate(bytes(err_buf), JOB_MAX_OUTPUT_BYTES)
            result = {
                "success": False,
                "output": _truncate(bytes(out_buf), JOB_MAX_OUTPUT_BYTES),
                "error": error,
                "duration_seconds": round(time.monotonic() - start, 3),
                "exit_code": None,
            }
            await asyncio.to_thread(complete_execution, exec_id, status="timeout", result=result)
            return result

        exit_code = proc.returncode
        result = {
            "success": exit_code == 0,
            "output": _truncate(bytes(out_buf), JOB_MAX_OUTPUT_BYTES),
            "error": _truncate(bytes(err_buf), JOB_MAX_OUTPUT_BYTES),
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
            "output": _truncate(bytes(out_buf), JOB_MAX_OUTPUT_BYTES),
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


async def _run_graph_job(exec_id: int, job_id: int, graph_type: str, params: dict) -> dict:
    """Run a LangGraph workflow in-process, mirroring the subprocess result contract."""
    # Lazy import: the scheduler must stay usable without the graphs/LLM stack loaded.
    from services.graphs.runtime import dispatch

    graph_inputs = params.get("graph_inputs") or {}
    start = time.monotonic()
    try:
        timeout = float(params.get("timeout", JOB_DEFAULT_TIMEOUT))
        try:
            output = await asyncio.wait_for(dispatch(graph_type, graph_inputs), timeout=timeout)
        except asyncio.TimeoutError:
            result = {
                "success": False,
                "output": "",
                "error": f"timed out after {timeout}s",
                "duration_seconds": round(time.monotonic() - start, 3),
                "exit_code": None,
            }
            await asyncio.to_thread(complete_execution, exec_id, status="timeout", result=result)
            return result

        result = {
            "success": True,
            "output": _truncate(output.encode("utf-8"), JOB_MAX_OUTPUT_BYTES),
            "error": "",
            "duration_seconds": round(time.monotonic() - start, 3),
            "exit_code": None,
        }
        await asyncio.to_thread(complete_execution, exec_id, status="success", result=result)
        return result
    except asyncio.CancelledError:
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
    except Exception as exc:  # noqa: BLE001 - graph failures must not crash the scheduler
        log.exception("job %s graph execution raised", job_id)
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
