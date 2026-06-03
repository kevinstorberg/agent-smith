"""Job execution model for tracking execution history."""
from __future__ import annotations

from psycopg2.extras import RealDictCursor

from services.db import get_connection
from services.api.models.base import BaseModel


class JobExecutionModel(BaseModel):
    """Model for job_executions table."""

    table = "job_executions"
    json_fields = {"result"}

    @classmethod
    def create(cls, job_id: int, status: str = "running") -> int:
        """Create a new job execution."""
        cls._validate_id(job_id)
        return super().create(job_id=job_id, status=status)

    @classmethod
    def complete(
        cls,
        execution_id: int,
        status: str,
        result: dict,
    ) -> None:
        """Complete an execution with results."""
        cls._validate_id(execution_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""UPDATE {cls.table} SET
                        status = %s,
                        completed_at = now(),
                        result = %s,
                        updated_at = now()
                    WHERE id = %s""",
                    (status, result, execution_id),
                )

    @classmethod
    def list_for_job(
        cls, job_id: int, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict], int]:
        """Get execution history for a specific job."""
        cls._validate_id(job_id)
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"SELECT COUNT(*) as cnt FROM {cls.table} WHERE job_id = %s",
                    (job_id,),
                )
                total = cur.fetchone()["cnt"]
                cur.execute(
                    f"""SELECT * FROM {cls.table}
                    WHERE job_id = %s
                    ORDER BY started_at DESC
                    LIMIT %s OFFSET %s""",
                    (job_id, limit, offset),
                )
                items = [cls.serialize_timestamps(dict(r)) for r in cur.fetchall()]
        return items, total


# Convenience exports
create_execution = JobExecutionModel.create
get_execution = JobExecutionModel.read
complete_execution = JobExecutionModel.complete
list_executions_for_job = JobExecutionModel.list_for_job
