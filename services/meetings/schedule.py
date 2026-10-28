from __future__ import annotations

import math

from psycopg2.extras import Json, RealDictCursor

from services.db import get_connection
from services.jobs.models.config import JobConfigModel
from services.jobs.models.job import BackgroundJobModel
from services.jobs.service import validate_input_params
from services.meetings.config import load_source_config


def configure_schedule(source: str, device: str, interval_minutes: float = 15) -> int:
    config = load_source_config(source)
    if (not isinstance(device, str) or not device.strip() or len(device) > 100
            or any(char in device for char in "*?[]")):
        raise ValueError("Meeting schedule requires one explicit device name without wildcard patterns")
    if (isinstance(interval_minutes, bool) or not isinstance(interval_minutes, (int, float))
            or not math.isfinite(interval_minutes) or interval_minutes <= 0):
        raise ValueError("Meeting schedule interval_minutes must be a finite positive number")
    name = f"Meetings: {config.name}"
    interval = {"minutes": interval_minutes}
    params = {"graph_type": "meeting_ingest", "graph_inputs": {"source": config.name}, "timeout": 300}
    validate_input_params(params)
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SET LOCAL statement_timeout = '5s'")
        cur.execute("SET LOCAL lock_timeout = '1s'")
        # Serialize repeated setup before the job exists, as well as after creation.
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (name,))
        cur.execute("SELECT * FROM background_jobs WHERE name = %s FOR UPDATE", (name,))
        existing = cur.fetchone()
        if existing:
            old = existing["input_params"] or {}
            if (existing["state"] != "active" or old.get("graph_type") != "meeting_ingest"
                    or old.get("graph_inputs") != {"source": config.name}):
                raise ValueError("Meeting schedule name belongs to a different job; rename that job first")
            job_id = existing["id"]
            cur.execute(
                """UPDATE background_jobs SET schedule_config = %s, input_params = %s,
                   version = version + 1, updated_at = clock_timestamp()
                   WHERE id = %s AND (schedule_config IS DISTINCT FROM %s OR input_params IS DISTINCT FROM %s)""",
                (Json(interval), Json(params), job_id, Json(interval), Json(params)),
            )
        else:
            job_id = BackgroundJobModel.create(
                name=name, schedule_config=interval, input_params=params,
                description="Import provider meeting summaries as context", conn=conn,
            )
        cur.execute("SELECT device, repo, enabled, exclude FROM job_configs WHERE job_id = %s", (job_id,))
        configs = [dict(row) for row in cur.fetchall()]
        expected = {"device": device, "repo": "*", "enabled": True, "exclude": False}
        if configs != [expected]:
            # Generic jobs intentionally default to '*'; account imports have one owner.
            cur.execute("DELETE FROM job_configs WHERE job_id = %s", (job_id,))
            JobConfigModel.create(job_id=job_id, device=device, conn=conn)
        return job_id
