from __future__ import annotations

from sqlalchemy import delete, func, select

from db.models.agent_smith import BackgroundJob, JobConfig, JobExecution
from db.repository import BaseRepository
from src.agent_smith.serialization import model_to_dict


class JobRepository(BaseRepository[BackgroundJob]):
    model = BackgroundJob

    async def list_page(self, *, limit: int, offset: int) -> tuple[list[dict], int]:
        total_result = await self.session.execute(select(func.count()).select_from(BackgroundJob))
        result = await self.session.execute(
            select(BackgroundJob).order_by(BackgroundJob.updated_at.desc()).limit(limit).offset(offset)
        )
        return [model_to_dict(row) for row in result.scalars().all()], int(total_result.scalar_one())

    async def get_detail(self, job_id: int) -> dict | None:
        job = await self.get(job_id)
        if job is None:
            return None
        row = model_to_dict(job)
        row["configs"] = await JobConfigRepository(self.session).list_for_job(job_id)
        return row

    async def delete_by_id(self, job_id: int) -> bool:
        result = await self.session.execute(
            delete(BackgroundJob).where(BackgroundJob.id == job_id).returning(BackgroundJob.id)
        )
        return result.scalar_one_or_none() is not None


class JobConfigRepository(BaseRepository[JobConfig]):
    model = JobConfig

    async def list_for_job(self, job_id: int) -> list[dict]:
        result = await self.session.execute(select(JobConfig).where(JobConfig.job_id == job_id).order_by(JobConfig.id))
        return [model_to_dict(row) for row in result.scalars().all()]


class JobExecutionRepository(BaseRepository[JobExecution]):
    model = JobExecution

    async def create_running(self, *, job_id: int, device: str) -> int:
        execution = JobExecution(job_id=job_id, status="running", device=device)
        self.add(execution)
        await self.session.flush()
        return execution.id

    async def complete(self, execution_id: int, *, status: str, result: dict) -> None:
        execution = await self.get(execution_id)
        if execution is None:
            raise KeyError(f"Execution not found: {execution_id}")
        execution.status = status
        execution.result = result
        from datetime import datetime, timezone

        execution.completed_at = datetime.now(timezone.utc)

    async def list_for_job(self, job_id: int, *, limit: int, offset: int) -> tuple[list[dict], int]:
        total_result = await self.session.execute(
            select(func.count()).select_from(JobExecution).where(JobExecution.job_id == job_id)
        )
        result = await self.session.execute(
            select(JobExecution)
            .where(JobExecution.job_id == job_id)
            .order_by(JobExecution.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [model_to_dict(row) for row in result.scalars().all()], int(total_result.scalar_one())

    async def reconcile_running(self, *, device: str) -> int:
        result = await self.session.execute(
            select(JobExecution).where(JobExecution.status == "running", JobExecution.device == device)
        )
        rows = result.scalars().all()
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        for row in rows:
            row.status = "interrupted"
            row.completed_at = now
        return len(rows)
