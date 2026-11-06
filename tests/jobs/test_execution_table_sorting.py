from datetime import datetime, timedelta, timezone
from functools import cmp_to_key

from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2.extras import Json
import pytest

from services.db import get_connection
from services.jobs.models.execution import list_executions_for_job
from services.api.routers.jobs import router


@pytest.fixture
def execution_rows():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO background_jobs(name,schedule_config,input_params) VALUES('Sort fixture','{}','{}') RETURNING id"
        )
        job = cur.fetchone()[0]
        rows = []
        for index, code in enumerate([10, 2, -1, None, "bad", {"bad": 1}, 0, 2]):
            started = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
                days=index % 3
            )
            completed = None if index % 4 == 0 else started + timedelta(hours=index % 2)
            status = ("success", "failed", "running")[index % 3]
            cur.execute(
                "INSERT INTO job_executions(job_id,status,started_at,completed_at,result) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                (job, status, started, completed, Json({"exit_code": code})),
            )
            rows.append(
                {
                    "id": cur.fetchone()[0],
                    "status": status,
                    "started": started,
                    "completed": completed,
                    "exit": code if isinstance(code, int) else None,
                }
            )
    yield job, rows
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM job_executions WHERE job_id=%s", (job,))
        cur.execute("DELETE FROM background_jobs WHERE id=%s", (job,))


@pytest.mark.parametrize("field", ["status", "started", "completed", "exit"])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_execution_sort_is_global_null_last_and_read_only(
    execution_rows, field, direction
):
    job, rows = execution_rows
    factor = 1 if direction == "asc" else -1

    def compare(a, b):
        x, y = a[field], b[field]
        if (x is None) != (y is None):
            return 1 if x is None else -1
        value = 0 if x is None else (x > y) - (x < y)
        return factor * (value or ((a["id"] > b["id"]) - (a["id"] < b["id"])))

    expected = sorted(rows, key=cmp_to_key(compare))
    before = list_executions_for_job(job, limit=100)[0]
    pages = [
        list_executions_for_job(
            job, limit=3, offset=offset, sort=f"{field}_{direction}"
        )
        for offset in (0, 3, 6)
    ]
    assert [item["id"] for page, total in pages for item in page] == [
        row["id"] for row in expected
    ]
    assert all(total == 8 for _, total in pages)
    assert list_executions_for_job(job, limit=100)[0] == before


def test_execution_route_rejects_invalid_order_before_query(execution_rows):
    job, _ = execution_rows
    app = FastAPI()
    app.include_router(router, prefix="/jobs")
    client = TestClient(app)
    assert (
        client.get(f"/jobs/{job}/executions", params={"sort": "exit_desc"}).status_code
        == 200
    )
    assert (
        client.get(
            f"/jobs/{job}/executions",
            params={"sort": "result;DROP TABLE job_executions"},
        ).status_code
        == 422
    )
