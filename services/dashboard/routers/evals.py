from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from psycopg2.extras import RealDictCursor

from services.db import get_connection

router = APIRouter()


def _build_filters(scenario="", model="", eval_type="", date_from="", date_to=""):
    conditions, params = [], []
    if scenario:
        conditions.append("scenario = %s")
        params.append(scenario)
    if model:
        conditions.append("test_model = %s")
        params.append(model)
    if eval_type:
        conditions.append("eval_type = %s")
        params.append(eval_type)
    if date_from:
        conditions.append("timestamp >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("timestamp <= %s")
        params.append(date_to)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where, params


def _serialize_timestamps(row):
    row["timestamp"] = row["timestamp"].isoformat()
    row["created_at"] = row["created_at"].isoformat()
    return row


@router.get("")
def list_evals(
    scenario: str = Query(""),
    model: str = Query(""),
    eval_type: str = Query(""),
    date_from: str = Query(""),
    date_to: str = Query(""),
    limit: int = Query(10, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    where, params = _build_filters(scenario, model, eval_type, date_from, date_to)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT count(*) as cnt FROM eval_results {where}", params)
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"SELECT id, timestamp, eval_type, scenario, test_model, judge_model, "
                f"threshold, results, created_at "
                f"FROM eval_results {where} "
                f"ORDER BY timestamp DESC LIMIT %s OFFSET %s",
                params + [limit, offset],
            )
            rows = cur.fetchall()

    return {"items": [_serialize_timestamps(row) for row in rows], "total": total}


@router.get("/categories")
def list_categories():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT eval_type FROM eval_results ORDER BY eval_type")
            return [row[0] for row in cur.fetchall()]


def _fetch_chart_rows(scenario: str, model: str, eval_type: str) -> list[dict]:
    where, params = _build_filters(scenario, model, eval_type)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT id, timestamp, results "
                f"FROM eval_results {where} "
                f"ORDER BY timestamp ASC",
                params,
            )
            return cur.fetchall()


@router.get("/chart")
def chart_data(
    scenario: str = Query(""),
    model: str = Query(""),
    eval_type: str = Query(""),
):
    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"].isoformat(),
            "scores": {r["rule"]: r["score"] for r in row["results"]},
        }
        for row in _fetch_chart_rows(scenario, model, eval_type)
    ]


@router.get("/chart/average")
def chart_average(
    scenario: str = Query(""),
    model: str = Query(""),
    eval_type: str = Query(""),
):
    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"].isoformat(),
            "score": sum(r["score"] for r in row["results"]) / max(len(row["results"]), 1),
        }
        for row in _fetch_chart_rows(scenario, model, eval_type)
    ]


@router.get("/{eval_id}")
def get_eval(eval_id: int):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM eval_results WHERE id = %s", (eval_id,))
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Eval not found")

    return _serialize_timestamps(row)
