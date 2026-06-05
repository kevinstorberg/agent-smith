"""Service-layer helpers for background jobs (the management boundary).

Creating a job here also creates a default '*'/'*' config so the job runs
everywhere by default — mirroring the harness convention where creating an item
also creates a default deployment config. Callers narrow scope afterward. The
underlying model (``services.jobs.models.job.create_job``) stays pure and does
not create configs on its own.

Both inserts run in a single transaction so a job can never be committed without
its default config (which would leave it unschedulable forever).
"""
from __future__ import annotations

from services.db import get_connection
from services.jobs.models.config import JobConfigModel
from services.jobs.models.job import BackgroundJobModel


def require_command(input_params: dict | None) -> None:
    """Every job is a shell command, so a command is mandatory at creation.

    Raises ValueError (which the REST layer surfaces as 422) if missing.
    """
    if not (input_params or {}).get("command"):
        raise ValueError("input_params.command is required")


def create_job_with_default_config(
    name: str,
    schedule_config: dict,
    input_params: dict | None = None,
    description: str | None = None,
) -> int:
    with get_connection() as conn:
        job_id = BackgroundJobModel.create(
            name=name,
            schedule_config=schedule_config,
            input_params=input_params or {},
            description=description,
            conn=conn,
        )
        JobConfigModel.create(job_id=job_id, device="*", repo="*", enabled=True, exclude=False, conn=conn)
    return job_id
