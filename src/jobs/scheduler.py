import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.jobs.base import BaseJob

logger = logging.getLogger(__name__)


@dataclass
class RegisteredJob:
    job: BaseJob
    trigger: str
    kwargs: dict


class JobScheduler:
    def __init__(self, scheduler: AsyncIOScheduler | None = None):
        self._scheduler = scheduler or AsyncIOScheduler()
        self._registered_jobs: list[RegisteredJob] = []
        self._running = False

    @property
    def registered_jobs(self) -> list[RegisteredJob]:
        return self._registered_jobs

    @property
    def running(self) -> bool:
        return self._running

    def register(self, job: BaseJob, *, trigger: str = "interval", **kwargs) -> None:
        self._registered_jobs.append(RegisteredJob(job=job, trigger=trigger, kwargs=kwargs))

    def add_job(
        self,
        func: Callable[..., Awaitable[None]],
        *,
        job_id: str,
        trigger: str,
        replace_existing: bool = True,
        **kwargs: Any,
    ) -> None:
        self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            replace_existing=replace_existing,
            **kwargs,
        )

    def get_job(self, job_id: str):
        return self._scheduler.get_job(job_id)

    def scheduled_jobs(self):
        return self._scheduler.get_jobs()

    async def start(self) -> None:
        for reg in self._registered_jobs:
            self._scheduler.add_job(
                self._build_job_runner(reg.job),
                trigger=reg.trigger,
                id=reg.job.name,
                **reg.kwargs,
            )
        if not self._scheduler.running:
            self._scheduler.start()
        self._running = True

    def _build_job_runner(self, job: BaseJob) -> Callable[[], Awaitable[None]]:
        async def run_job() -> None:
            await self._safe_execute(job)

        return run_job

    async def _safe_execute(self, job: BaseJob) -> None:
        """Execute a job with error handling and optional timeout."""
        try:
            timeout = getattr(job, "timeout_seconds", None)
            if timeout:
                await asyncio.wait_for(job.execute(), timeout=timeout)
            else:
                await job.execute()
        except asyncio.TimeoutError:
            logger.error(f"Job '{job.name}' timed out after {job.timeout_seconds}s")
        except Exception:
            logger.exception(f"Job '{job.name}' failed")

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._running = False
