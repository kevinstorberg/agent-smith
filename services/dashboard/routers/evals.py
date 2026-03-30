from __future__ import annotations

from fastapi import APIRouter, Query
from psycopg2.extras import RealDictCursor

from services.db import get_connection
from services.db.base_model import BaseModel
from services.dashboard.routers.base import require_found

router = APIRouter()


def _build_filters(scenario="", model="", eval_type="", subcategory="", date_from="", date_to=""):
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
    if subcategory:
        conditions.append("subcategory = %s")
        params.append(subcategory)
    if date_from:
        conditions.append("timestamp >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("timestamp <= %s")
        params.append(date_to)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where, params


@router.get("")
def list_evals(
    scenario: str = Query(""),
    model: str = Query(""),
    eval_type: str = Query(""),
    subcategory: str = Query(""),
    date_from: str = Query(""),
    date_to: str = Query(""),
    limit: int = Query(10, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    where, params = _build_filters(scenario, model, eval_type, subcategory, date_from, date_to)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT count(*) as cnt FROM eval_results {where}", params)
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"SELECT id, timestamp, eval_type, subcategory, scenario, test_model, judge_model, "
                f"threshold, results, created_at "
                f"FROM eval_results {where} "
                f"ORDER BY timestamp DESC LIMIT %s OFFSET %s",
                params + [limit, offset],
            )
            rows = cur.fetchall()

    return {"items": [BaseModel.serialize_timestamps(row) for row in rows], "total": total}


@router.get("/categories")
def list_categories():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT eval_type FROM eval_results ORDER BY eval_type")
            return [row[0] for row in cur.fetchall()]


@router.get("/subcategories")
def list_subcategories(eval_type: str = Query("")):
    with get_connection() as conn:
        with conn.cursor() as cur:
            if eval_type:
                cur.execute(
                    "SELECT DISTINCT subcategory FROM eval_results "
                    "WHERE eval_type = %s AND subcategory IS NOT NULL "
                    "ORDER BY subcategory",
                    (eval_type,),
                )
            else:
                cur.execute(
                    "SELECT DISTINCT subcategory FROM eval_results "
                    "WHERE subcategory IS NOT NULL "
                    "ORDER BY subcategory"
                )
            return [row[0] for row in cur.fetchall()]


def _fetch_chart_rows(scenario: str, model: str, eval_type: str, subcategory: str = "") -> list[dict]:
    where, params = _build_filters(scenario, model, eval_type, subcategory)
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
    subcategory: str = Query(""),
):
    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"].isoformat(),
            "scores": {r["rule"]: r["score"] for r in row["results"]},
        }
        for row in _fetch_chart_rows(scenario, model, eval_type, subcategory)
    ]


@router.get("/chart/average")
def chart_average(
    scenario: str = Query(""),
    model: str = Query(""),
    eval_type: str = Query(""),
    subcategory: str = Query(""),
):
    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"].isoformat(),
            "score": sum(r["score"] for r in row["results"]) / max(len(row["results"]), 1),
        }
        for row in _fetch_chart_rows(scenario, model, eval_type, subcategory)
    ]


@router.get("/{eval_id}")
def get_eval(eval_id: int):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM eval_results WHERE id = %s", (eval_id,))
            row = cur.fetchone()

    return BaseModel.serialize_timestamps(require_found(row, "Eval", eval_id))


@router.delete("/{eval_id}")
def delete_eval(eval_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM eval_results WHERE id = %s RETURNING id", (eval_id,))
            row = cur.fetchone()

    require_found(row, "Eval", eval_id)
    return {"deleted": eval_id}
