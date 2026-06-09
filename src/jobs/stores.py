from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from db.connection import get_engine
from src.jobs.definitions import JobDefinition


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobRunStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SKIPPED_LOCK = "skipped_lock"
    DISABLED = "disabled"


@dataclass(frozen=True)
class JobRunRecord:
    run_id: str
    job_name: str
    status: JobRunStatus
    source: str
    attempt: int = 1
    max_attempts: int = 1
    started_at: datetime = field(default_factory=_utc_now)
    finished_at: datetime | None = None
    duration_ms: float | None = None
    error: str | None = None


class JobStatusStore(Protocol):
    async def start_run(self, definition: JobDefinition, *, source: str, attempt: int) -> JobRunRecord: ...
    async def finish_run(
        self,
        run_id: str,
        *,
        status: JobRunStatus,
        error: str | None = None,
    ) -> JobRunRecord: ...
    async def list_runs(self, job_name: str | None = None, *, limit: int = 50) -> Sequence[JobRunRecord]: ...


class InMemoryJobStatusStore:
    def __init__(self) -> None:
        self._runs: list[JobRunRecord] = []

    async def start_run(self, definition: JobDefinition, *, source: str, attempt: int) -> JobRunRecord:
        record = JobRunRecord(
            run_id=str(uuid4()),
            job_name=definition.name,
            status=JobRunStatus.RUNNING,
            source=source,
            attempt=attempt,
            max_attempts=definition.retry_policy.max_attempts,
        )
        self._runs.append(record)
        return record

    async def finish_run(
        self,
        run_id: str,
        *,
        status: JobRunStatus,
        error: str | None = None,
    ) -> JobRunRecord:
        for index, record in enumerate(self._runs):
            if record.run_id == run_id:
                finished_at = _utc_now()
                updated = replace(
                    record,
                    status=status,
                    finished_at=finished_at,
                    duration_ms=(finished_at - record.started_at).total_seconds() * 1000,
                    error=error,
                )
                self._runs[index] = updated
                return updated
        raise KeyError(f"Unknown job run_id: {run_id}")

    async def list_runs(self, job_name: str | None = None, *, limit: int = 50) -> Sequence[JobRunRecord]:
        runs = self._runs
        if job_name is not None:
            runs = [run for run in runs if run.job_name == job_name]
        return list(reversed(runs[-limit:]))


class PostgresJobStatusStore:
    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self._engine = engine

    async def ensure_schema(self) -> None:
        engine = self._engine or get_engine()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS cairn_job_runs (
                        run_id TEXT PRIMARY KEY,
                        job_name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        source TEXT NOT NULL,
                        attempt INTEGER NOT NULL,
                        max_attempts INTEGER NOT NULL,
                        started_at TIMESTAMPTZ NOT NULL,
                        finished_at TIMESTAMPTZ,
                        duration_ms DOUBLE PRECISION,
                        error TEXT
                    )
                    """
                )
            )

    async def start_run(self, definition: JobDefinition, *, source: str, attempt: int) -> JobRunRecord:
        record = JobRunRecord(
            run_id=str(uuid4()),
            job_name=definition.name,
            status=JobRunStatus.RUNNING,
            source=source,
            attempt=attempt,
            max_attempts=definition.retry_policy.max_attempts,
        )
        engine = self._engine or get_engine()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO cairn_job_runs (
                        run_id, job_name, status, source, attempt, max_attempts, started_at
                    )
                    VALUES (
                        :run_id, :job_name, :status, :source, :attempt, :max_attempts, :started_at
                    )
                    """
                ),
                {
                    "run_id": record.run_id,
                    "job_name": record.job_name,
                    "status": record.status.value,
                    "source": record.source,
                    "attempt": record.attempt,
                    "max_attempts": record.max_attempts,
                    "started_at": record.started_at,
                },
            )
        return record

    async def finish_run(
        self,
        run_id: str,
        *,
        status: JobRunStatus,
        error: str | None = None,
    ) -> JobRunRecord:
        finished_at = _utc_now()
        engine = self._engine or get_engine()
        async with engine.begin() as connection:
            existing = await connection.execute(
                text("SELECT started_at FROM cairn_job_runs WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
            started_at = existing.scalar_one()
            duration_ms = (finished_at - started_at).total_seconds() * 1000
            await connection.execute(
                text(
                    """
                    UPDATE cairn_job_runs
                    SET status = :status,
                        finished_at = :finished_at,
                        duration_ms = :duration_ms,
                        error = :error
                    WHERE run_id = :run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "status": status.value,
                    "finished_at": finished_at,
                    "duration_ms": duration_ms,
                    "error": error,
                },
            )
            row = await connection.execute(
                text(
                    """
                    SELECT run_id, job_name, status, source, attempt, max_attempts,
                           started_at, finished_at, duration_ms, error
                    FROM cairn_job_runs
                    WHERE run_id = :run_id
                    """
                ),
                {"run_id": run_id},
            )
        return _record_from_row(row.one())

    async def list_runs(self, job_name: str | None = None, *, limit: int = 50) -> Sequence[JobRunRecord]:
        engine = self._engine or get_engine()
        where = "WHERE job_name = :job_name" if job_name else ""
        params = {"job_name": job_name, "limit": limit}
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    f"""
                    SELECT run_id, job_name, status, source, attempt, max_attempts,
                           started_at, finished_at, duration_ms, error
                    FROM cairn_job_runs
                    {where}
                    ORDER BY started_at DESC
                    LIMIT :limit
                    """
                ),
                params,
            )
        return [_record_from_row(row) for row in rows]


def _record_from_row(row) -> JobRunRecord:
    return JobRunRecord(
        run_id=row.run_id,
        job_name=row.job_name,
        status=JobRunStatus(row.status),
        source=row.source,
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        started_at=row.started_at,
        finished_at=row.finished_at,
        duration_ms=row.duration_ms,
        error=row.error,
    )
