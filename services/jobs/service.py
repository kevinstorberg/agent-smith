"""Service-layer helpers for background jobs (the management boundary).

Creating a job here also creates a default '*'/'*' config so the job runs
everywhere by default — mirroring the harness convention where creating an item
also creates a default deployment config. Callers narrow scope afterward. The
underlying model (``services.jobs.models.job.create_job``) stays pure and does
not create configs on its own.
"""
from __future__ import annotations

from services.jobs.models.config import create_config
from services.jobs.models.job import create_job as _create_job


def create_job_with_default_config(
    name: str,
    schedule_config: dict,
    input_params: dict | None = None,
    description: str | None = None,
) -> int:
    job_id = _create_job(
        name=name,
        schedule_config=schedule_config,
        input_params=input_params or {},
        description=description,
    )
    create_config(job_id=job_id, device="*", repo="*", enabled=True, exclude=False)
    return job_id
