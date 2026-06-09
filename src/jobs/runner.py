import asyncio
import inspect
import logging
from dataclasses import replace

from src.jobs.base import BaseJob
from src.jobs.context import JobContext
from src.jobs.definitions import JobDefinition
from src.jobs.locks import JobLockBackend
from src.jobs.stores import JobRunRecord, JobRunStatus, JobStatusStore

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(
        self,
        *,
        context: JobContext,
        status_store: JobStatusStore,
        lock_backend: JobLockBackend,
    ) -> None:
        self._context = context
        self._status_store = status_store
        self._lock_backend = lock_backend

    async def run(self, definition: JobDefinition, *, source: str = "scheduled") -> JobRunRecord:
        if not definition.enabled:
            record = await self._status_store.start_run(definition, source=source, attempt=1)
            return await self._status_store.finish_run(
                record.run_id,
                status=JobRunStatus.DISABLED,
                error="job is disabled",
            )

        lease = None
        if definition.lock_policy.enabled:
            lease = await self._lock_backend.acquire(
                definition.lock_key,
                ttl_seconds=definition.lock_policy.ttl_seconds,
            )
            if lease is None:
                record = await self._status_store.start_run(definition, source=source, attempt=1)
                return await self._status_store.finish_run(
                    record.run_id,
                    status=JobRunStatus.SKIPPED_LOCK,
                    error=f"lock not acquired: {definition.lock_key}",
                )

        try:
            return await self._run_with_retries(definition, source=source)
        finally:
            if lease is not None:
                await lease.release()

    async def _run_with_retries(self, definition: JobDefinition, *, source: str) -> JobRunRecord:
        last_record: JobRunRecord | None = None
        for attempt in range(1, definition.retry_policy.max_attempts + 1):
            record = await self._status_store.start_run(definition, source=source, attempt=attempt)
            try:
                job = definition.create_job()
                await self._execute_job(job, definition, source=source, attempt=attempt)
            except asyncio.TimeoutError:
                last_record = await self._status_store.finish_run(
                    record.run_id,
                    status=JobRunStatus.TIMED_OUT,
                    error=f"timed out after {definition.timeout_seconds}s",
                )
                logger.error("Job timed out", extra={"job_name": definition.name, "attempt": attempt})
            except Exception as e:
                last_record = await self._status_store.finish_run(
                    record.run_id,
                    status=JobRunStatus.FAILED,
                    error=str(e),
                )
                logger.exception("Job failed", extra={"job_name": definition.name, "attempt": attempt})
            else:
                return await self._status_store.finish_run(record.run_id, status=JobRunStatus.SUCCESS)

            if attempt < definition.retry_policy.max_attempts and definition.retry_policy.backoff_seconds:
                await asyncio.sleep(definition.retry_policy.backoff_seconds)

        if last_record is None:
            raise RuntimeError(f"Job {definition.name!r} did not record a terminal run")
        return last_record

    async def _execute_job(self, job: BaseJob, definition: JobDefinition, *, source: str, attempt: int) -> None:
        timeout = definition.timeout_seconds
        if timeout is None:
            timeout = getattr(job, "timeout_seconds", None)
        context = replace(
            self._context,
            metadata={
                **self._context.metadata,
                **definition.metadata,
                "job_name": definition.name,
                "source": source,
                "attempt": attempt,
            },
        )

        async def execute() -> None:
            await _call_job_execute(job, context)

        if timeout:
            await asyncio.wait_for(execute(), timeout=timeout)
        else:
            await execute()


async def _call_job_execute(job: BaseJob, context: JobContext) -> None:
    signature = inspect.signature(job.execute)
    if not signature.parameters:
        await job.execute()
    else:
        await job.execute(context)
