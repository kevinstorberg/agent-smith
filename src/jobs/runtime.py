import logging
from collections.abc import Mapping
from typing import Any

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from cache.backends import get_cache_backend
from config.models import DefaultConfig
from db.migrations.utils import sync_database_url
from db.unit_of_work import UnitOfWorkFactory
from src.jobs.context import JobContext
from src.jobs.definitions import JobDefinition
from src.jobs.locks import JobLockBackend, create_lock_backend
from src.jobs.registry import discover_jobs, registered_jobs
from src.jobs.runner import JobRunner
from src.jobs.scheduler import JobScheduler
from src.jobs.stores import InMemoryJobStatusStore, JobRunRecord, JobStatusStore, PostgresJobStatusStore
from src.settings import Settings

logger = logging.getLogger(__name__)

_ACTIVE_RUNTIME: "JobRuntime | None" = None


class JobRuntime:
    def __init__(
        self,
        *,
        config: DefaultConfig,
        settings: Settings,
        scheduler: JobScheduler,
        status_store: JobStatusStore,
        lock_backend: JobLockBackend,
        definitions: Mapping[str, JobDefinition] | None = None,
    ) -> None:
        self.config = config
        self.settings = settings
        self.scheduler = scheduler
        self.status_store = status_store
        self.lock_backend = lock_backend
        self.definitions: dict[str, JobDefinition] = dict(definitions or {})
        self._started = False
        self._runner = JobRunner(
            context=JobContext(
                config=config,
                settings=settings,
                unit_of_work_factory=UnitOfWorkFactory(),
                cache_backend=get_cache_backend(),
            ),
            status_store=status_store,
            lock_backend=lock_backend,
        )

    @property
    def running(self) -> bool:
        return self.scheduler.running

    async def start(self) -> None:
        if not self.config.jobs.enabled:
            logger.info("Job runtime disabled")
            return

        global _ACTIVE_RUNTIME
        _ACTIVE_RUNTIME = self

        if self.config.jobs.auto_discover:
            self.definitions.update(discover_jobs())

        if hasattr(self.status_store, "ensure_schema"):
            await self.status_store.ensure_schema()

        persistent_scheduler = self.config.jobs.scheduler_store == "postgres"
        for definition in self.definitions.values():
            if not definition.enabled:
                continue
            if persistent_scheduler:
                definition.validate_for_persistent_store()
            self.scheduler.add_job(
                run_registered_job,
                job_id=definition.name,
                trigger=definition.trigger,
                args=[definition.name],
                **definition.trigger_kwargs,
            )

        await self.scheduler.start()
        self._started = True
        logger.info("Job runtime started", extra={"job_count": len(self.definitions)})

    async def shutdown(self) -> None:
        global _ACTIVE_RUNTIME
        if _ACTIVE_RUNTIME is self:
            _ACTIVE_RUNTIME = None
        await self.scheduler.shutdown()
        self._started = False
        logger.info("Job runtime stopped")

    async def run_job(self, job_name: str, *, source: str = "manual") -> JobRunRecord:
        definition = self.definitions.get(job_name)
        if definition is None:
            raise KeyError(f"Unknown job: {job_name}")
        return await self._runner.run(definition, source=source)

    async def list_runs(self, job_name: str | None = None, *, limit: int = 50):
        return await self.status_store.list_runs(job_name, limit=limit)

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs = []
        for definition in self.definitions.values():
            scheduled = self.scheduler.get_job(definition.name)
            jobs.append(
                {
                    "name": definition.name,
                    "enabled": definition.enabled,
                    "trigger": definition.trigger,
                    "trigger_kwargs": definition.trigger_kwargs,
                    "factory": definition.factory,
                    "next_run_time": getattr(scheduled, "next_run_time", None),
                    "timeout_seconds": definition.timeout_seconds,
                    "max_attempts": definition.retry_policy.max_attempts,
                    "lock_enabled": definition.lock_policy.enabled,
                    "lock_key": definition.lock_key,
                }
            )
        return jobs

    def health(self) -> dict[str, Any]:
        return {
            "enabled": self.config.jobs.enabled,
            "running": self.running,
            "job_count": len(self.definitions),
            "scheduler_store": self.config.jobs.scheduler_store,
            "status_store": self.config.jobs.status_store,
            "lock_backend": self.config.jobs.lock_backend,
        }


async def run_registered_job(job_name: str) -> None:
    if _ACTIVE_RUNTIME is None:
        raise RuntimeError("No active JobRuntime is available")
    await _ACTIVE_RUNTIME.run_job(job_name, source="scheduled")


def create_job_runtime(
    config: DefaultConfig,
    settings: Settings,
    *,
    definitions: Mapping[str, JobDefinition] | None = None,
) -> JobRuntime:
    scheduler = JobScheduler(_create_scheduler(config, settings))
    status_store = _create_status_store(config)
    lock_backend = create_lock_backend(config.jobs.lock_backend, redis_url=settings.REDIS_URL)
    runtime_definitions = dict(registered_jobs())
    if definitions:
        runtime_definitions.update(definitions)
    return JobRuntime(
        config=config,
        settings=settings,
        scheduler=scheduler,
        status_store=status_store,
        lock_backend=lock_backend,
        definitions=runtime_definitions,
    )


async def start_job_runtime(app: FastAPI) -> JobRuntime:
    runtime = create_job_runtime(app.state.config, app.state.settings)
    app.state.job_runtime = runtime
    await runtime.start()
    return runtime


async def shutdown_job_runtime(app: FastAPI) -> None:
    runtime = getattr(app.state, "job_runtime", None)
    if runtime is not None:
        await runtime.shutdown()


def _create_scheduler(config: DefaultConfig, settings: Settings) -> AsyncIOScheduler:
    if config.jobs.scheduler_store == "memory":
        return AsyncIOScheduler()
    if config.jobs.scheduler_store == "postgres":
        return AsyncIOScheduler(
            jobstores={
                "default": SQLAlchemyJobStore(url=sync_database_url(settings.database_url)),
            }
        )
    raise ValueError(f"Unknown jobs.scheduler_store: {config.jobs.scheduler_store!r}")


def _create_status_store(config: DefaultConfig) -> JobStatusStore:
    if config.jobs.status_store == "memory":
        return InMemoryJobStatusStore()
    if config.jobs.status_store == "postgres":
        return PostgresJobStatusStore()
    raise ValueError(f"Unknown jobs.status_store: {config.jobs.status_store!r}")
