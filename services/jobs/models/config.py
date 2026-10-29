"""Job config model for device/repo scoping."""
from __future__ import annotations

from psycopg2.extras import RealDictCursor

from services.db import get_connection
from services.api.models.base import BaseModel


class JobConfigModel(BaseModel):
    """Model for job_configs table."""

    table = "job_configs"

    @classmethod
    def create(
        cls,
        job_id: int,
        device: str = "*",
        repo: str = "*",
        enabled: bool = True,
        exclude: bool = False,
        conn=None,
    ) -> int:
        cls._validate_id(job_id)
        return super().create(
            conn=conn,
            job_id=job_id,
            device=device,
            repo=repo,
            enabled=enabled,
            exclude=exclude,
        )

    @classmethod
    def update(cls, config_id: int, **fields) -> None:
        clean = cls._collect_fields(**fields)
        if clean:
            cls.dynamic_update(config_id, clean)

    @classmethod
    def list_for_job(cls, job_id: int) -> list[dict]:
        return cls.list_for_jobs([job_id])

    @classmethod
    def list_for_jobs(cls, job_ids: list[int]) -> list[dict]:
        for job_id in job_ids:
            cls._validate_id(job_id)
        if not job_ids:
            return []
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"SELECT * FROM {cls.table} WHERE job_id = ANY(%s) ORDER BY id",
                    (job_ids,),
                )
                return [cls.serialize_timestamps(dict(r)) for r in cur.fetchall()]


# Convenience exports
list_configs = JobConfigModel.list_for_job
list_configs_for_jobs = JobConfigModel.list_for_jobs
get_config = JobConfigModel.read
create_config = JobConfigModel.create
update_config = JobConfigModel.update
delete_config = JobConfigModel.destroy
