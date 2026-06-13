"""Background job model."""
from __future__ import annotations

from services.api.models.base import BaseModel
from services.jobs.schedule import parse_interval


class BackgroundJobModel(BaseModel):
    """Model for background_jobs table.

    Listing only returns active rows: proposed/rejected rows (improvement
    proposals awaiting review) must stay invisible to the scheduler, REST
    list, and MCP list. ``read`` by id intentionally still returns them so
    the proposals service can inspect a proposed row.
    """

    table = "background_jobs"
    json_fields = {"schedule_config", "input_params"}

    @classmethod
    def list(
        cls,
        columns: str = "*",
        where: str = "WHERE state = 'active'",
        params: tuple = (),
        order_by: str = "updated_at DESC",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        return super().list(
            columns=columns, where=where, params=params,
            order_by=order_by, limit=limit, offset=offset,
        )

    @classmethod
    def create(
        cls,
        name: str,
        schedule_config: dict,
        input_params: dict,
        description: str | None = None,
        conn=None,
    ) -> int:
        """Create a new background job."""
        cls._validate_required(
            {"name": name, "schedule_config": schedule_config},
            ["name", "schedule_config"],
        )
        parse_interval(schedule_config)
        return super().create(
            conn=conn,
            name=name,
            description=description,
            schedule_config=schedule_config,
            input_params=input_params,
        )

    @classmethod
    def get_by_name(cls, name: str) -> dict | None:
        """Return the active job with this name, if any."""
        items, _ = cls.list(where="WHERE state = 'active' AND name = %s", params=(name,), limit=1)
        return items[0] if items else None

    @classmethod
    def update(cls, job_id: int, **fields) -> None:
        """Update a background job, bumping its version for optimistic concurrency."""
        clean = cls._collect_fields(**fields)
        if "schedule_config" in clean:
            parse_interval(clean["schedule_config"])
        if not clean:
            return
        current = cls.read(job_id)
        assert current, f"Job not found: {job_id}"
        clean["version"] = current["version"] + 1
        cls.dynamic_update(job_id, clean)


# Convenience exports
list_jobs = BackgroundJobModel.list
get_job = BackgroundJobModel.read
get_job_by_name = BackgroundJobModel.get_by_name
create_job = BackgroundJobModel.create
update_job = BackgroundJobModel.update
delete_job = BackgroundJobModel.destroy
