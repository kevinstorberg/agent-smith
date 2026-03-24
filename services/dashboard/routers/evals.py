from __future__ import annotations

from fastapi import APIRouter, Query
from psycopg2.extras import RealDictCursor

from services.db import get_connection

router = APIRouter()


@router.get("")
def list_evals(
    scenario: str = Query(""),
    model: str = Query(""),
    date_from: str = Query(""),
    date_to: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
):
    conditions = []
    params = []

    if scenario:
        conditions.append("scenario = %s")
        params.append(scenario)
    if model:
        conditions.append("test_model = %s")
        params.append(model)
    if date_from:
        conditions.append("timestamp >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("timestamp <= %s")
        params.append(date_to)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT id, timestamp, eval_type, scenario, test_model, judge_model, "
                f"threshold, results, created_at "
                f"FROM eval_results {where} "
                f"ORDER BY timestamp DESC LIMIT %s",
                params,
            )
            rows = cur.fetchall()

    for row in rows:
        row["timestamp"] = row["timestamp"].isoformat()
        row["created_at"] = row["created_at"].isoformat()

    return rows


@router.get("/chart")
def chart_data(
    scenario: str = Query(""),
    model: str = Query(""),
):
    conditions = []
    params = []

    if scenario:
        conditions.append("scenario = %s")
        params.append(scenario)
    if model:
        conditions.append("test_model = %s")
        params.append(model)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT id, timestamp, results "
                f"FROM eval_results {where} "
                f"ORDER BY timestamp ASC",
                params,
            )
            rows = cur.fetchall()

    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"].isoformat(),
            "scores": {
                r["rule"]: r["score"]
                for r in row["results"]
            },
        }
        for row in rows
    ]


@router.get("/{eval_id}")
def get_eval(eval_id: int):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM eval_results WHERE id = %s", (eval_id,))
            row = cur.fetchone()

    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Eval not found")

    row["timestamp"] = row["timestamp"].isoformat()
    row["created_at"] = row["created_at"].isoformat()
    return row
