"""Background job model."""

from __future__ import annotations

from psycopg2.extras import RealDictCursor

from services.api.models.base import BaseModel
from services.api.models.shared.listing import bidirectional_sorts, search_pattern, sort_clause
from services.db import get_connection
from services.jobs.schedule import parse_interval

JOB_SORTS = bidirectional_sorts({
    ('name', 'name_desc'): ('lower(name)',),
    ('updated_asc', 'updated'): ('updated_at',),
})
JOB_SORTS['newest'] = 'created_at DESC, id DESC'


class JobNotFoundError(LookupError):
    pass


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
        limit: int | None = 100,
        offset: int = 0,
        *,
        q: str | None = None,
        schedule_enabled: bool | None = None,
        sort: str | None = None,
    ) -> tuple[list[dict], int]:
        clauses, values = [], list(params)
        pattern = search_pattern(q)
        if pattern is not None:
            clauses.append("(name ILIKE %s OR description ILIKE %s)")
            values.extend([pattern, pattern])
        if schedule_enabled is not None:
            if type(schedule_enabled) is not bool:
                raise ValueError("schedule_enabled must be a boolean")
            clauses.append("schedule_enabled = %s")
            values.append(schedule_enabled)
        if clauses:
            where += (" AND " if where else "WHERE ") + " AND ".join(clauses)
        if sort is not None:
            order_by = sort_clause(sort, JOB_SORTS)
        return super().list(
            columns=columns,
            where=where,
            params=tuple(values),
            order_by=order_by,
            limit=limit,
            offset=offset,
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
        items, _ = cls.list(
            where="WHERE state = 'active' AND name = %s", params=(name,), limit=1
        )
        return items[0] if items else None

    @classmethod
    def list_for_graph(cls, graph_type: str) -> list[dict]:
        items, _ = cls.list(
            where="WHERE state = 'active' AND input_params->>'graph_type' = %s",
            params=(graph_type,),
            limit=None,
        )
        return items

    @classmethod
    def update(cls, job_id: int, **fields) -> None:
        """Update a job and its version under the same row lock."""
        clean = cls._collect_fields(**fields)
        if "schedule_config" in clean:
            parse_interval(clean["schedule_config"])
        if not clean:
            return
        cls._validate_id(job_id)
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT version FROM {cls.table} WHERE id=%s FOR UPDATE", (job_id,)
            )
            current = cur.fetchone()
            assert current, f"Job not found: {job_id}"
            clean["version"] = current[0] + 1
            cls.dynamic_update(job_id, clean, conn=conn)

    @classmethod
    def set_schedule_enabled(cls, job_id: int, schedule_enabled: bool) -> dict:
        if type(job_id) is not int or job_id <= 0:
            raise ValueError("Job id must be a positive integer")
        if type(schedule_enabled) is not bool:
            raise ValueError("schedule_enabled must be a boolean")
        with (
            get_connection() as conn,
            conn.cursor(cursor_factory=RealDictCursor) as cur,
        ):
            cur.execute(
                f"""UPDATE {cls.table}
                SET schedule_enabled=%s,
                    version=version+CASE WHEN schedule_enabled IS DISTINCT FROM %s THEN 1 ELSE 0 END,
                    updated_at=CASE WHEN schedule_enabled IS DISTINCT FROM %s THEN clock_timestamp() ELSE updated_at END
                WHERE id=%s AND state='active' RETURNING *""",
                (schedule_enabled, schedule_enabled, schedule_enabled, job_id),
            )
            row = cur.fetchone()
            if row is None:
                raise JobNotFoundError(f"Active job not found: {job_id}")
            return cls.serialize_timestamps(dict(row))


# Convenience exports
list_jobs = BackgroundJobModel.list
get_job = BackgroundJobModel.read
get_job_by_name = BackgroundJobModel.get_by_name
list_graph_jobs = BackgroundJobModel.list_for_graph
create_job = BackgroundJobModel.create
update_job = BackgroundJobModel.update
set_schedule_enabled = BackgroundJobModel.set_schedule_enabled
delete_job = BackgroundJobModel.destroy
