"""Background job model."""
from __future__ import annotations

from psycopg2.extras import RealDictCursor

from services.db import get_connection
from services.api.models.base import BaseModel


class BackgroundJobModel(BaseModel):
    """Model for background_jobs table."""

    table = "background_jobs"
    json_fields = {"schedule_config", "input_params"}

    @classmethod
    def create(
        cls,
        name: str,
        schedule_config: dict,
        input_params: dict,
        description: str | None = None,
    ) -> int:
        """Create a new background job."""
        cls._validate_required(
            {"name": name, "schedule_config": schedule_config},
            ["name", "schedule_config"],
        )
        return super().create(
            name=name,
            description=description,
            schedule_config=schedule_config,
            input_params=input_params,
        )

    @classmethod
    def update(cls, job_id: int, **fields) -> None:
        """Update a background job."""
        clean = cls._collect_fields(**fields)
        if clean:
            cls.dynamic_update(job_id, clean)


# Convenience exports
list_jobs = BackgroundJobModel.list
get_job = BackgroundJobModel.read
create_job = BackgroundJobModel.create
update_job = BackgroundJobModel.update
delete_job = BackgroundJobModel.destroy
