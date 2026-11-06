from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Query
from psycopg2.extras import RealDictCursor

from services.db import get_connection
from services.api.models.base import BaseModel
from services.api.routers.base import (
    require_found,
    list_response,
    delete_response,
    query_result,
)
from services.api.models.shared.listing import (
    bidirectional_sorts,
    search_pattern,
    sort_clause,
    sort_pattern,
)

RESULT_SORTS = {
    **bidirectional_sorts(
        {
            ("category_asc", "category_desc"): (
                "NULLIF(lower(eval_type), '')",
                "NULLIF(lower(subcategory), '')",
            ),
            ("scenario_asc", "scenario_desc"): ("NULLIF(lower(scenario), '')",),
            ("model_asc", "model_desc"): ("NULLIF(lower(test_model), '')",),
            ("threshold_asc", "threshold_desc"): ("threshold",),
            ("score_asc", "score"): ("score_avg",),
        }
    ),
    "newest": "timestamp DESC, id DESC",
    "oldest": "timestamp, id",
    "score": "score_avg DESC NULLS LAST, timestamp DESC, id DESC",
}

router = APIRouter()


def _build_filters(
    scenario="",
    model="",
    eval_type="",
    subcategory="",
    date_from="",
    date_to="",
    *,
    q: str | None = None,
):
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
    pattern = search_pattern(q)
    if pattern is not None:
        conditions.append(
            "(scenario ILIKE %s OR test_model ILIKE %s OR eval_type ILIKE %s OR subcategory ILIKE %s)"
        )
        params.extend([pattern] * 4)
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
    q: Annotated[str, Query(max_length=1000)] = "",
    sort: Annotated[str, Query(pattern=sort_pattern(RESULT_SORTS))] = "newest",
):
    where, params = query_result(
        _build_filters, scenario, model, eval_type, subcategory, date_from, date_to, q=q
    )
    order = query_result(sort_clause, sort, RESULT_SORTS)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT count(*) as cnt FROM eval_results {where}", params)
            total = cur.fetchone()["cnt"]

            cur.execute(
                f"SELECT id, timestamp, eval_type, subcategory, scenario, test_model, judge_model, "
                f"threshold, eval_suite_id, created_at, "
                f"(SELECT avg((r->>'score')::float) FROM jsonb_array_elements(results) r) AS score_avg, "
                f"jsonb_array_length(results) AS score_count "
                f"FROM eval_results {where} "
                f"ORDER BY {order} LIMIT %s OFFSET %s",
                params + [limit, offset],
            )
            rows = cur.fetchall()

    items = []
    for row in rows:
        item = BaseModel.serialize_timestamps(row)
        if item.get("score_avg") is not None:
            item["score_avg"] = round(item["score_avg"], 3)
        else:
            item["score_avg"] = 0
        items.append(item)
    return list_response(items, total)


@router.get("/categories")
def list_categories():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT eval_type FROM eval_results ORDER BY eval_type"
            )
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


def _fetch_chart_rows(
    scenario: str,
    model: str,
    eval_type: str,
    subcategory: str = "",
    *,
    q: str | None = None,
) -> list[dict]:
    where, params = _build_filters(scenario, model, eval_type, subcategory, q=q)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT id, timestamp, results "
                f"FROM eval_results {where} "
                f"ORDER BY timestamp ASC, id ASC",
                params,
            )
            return cur.fetchall()


@router.get("/chart")
def chart_data(
    scenario: str = Query(""),
    model: str = Query(""),
    eval_type: str = Query(""),
    subcategory: str = Query(""),
    q: Annotated[str, Query(max_length=1000)] = "",
):
    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"].isoformat(),
            "scores": {r["rule"]: r["score"] for r in row["results"]},
        }
        for row in query_result(
            _fetch_chart_rows, scenario, model, eval_type, subcategory, q=q
        )
    ]


@router.get("/chart/average")
def chart_average(
    scenario: str = Query(""),
    model: str = Query(""),
    eval_type: str = Query(""),
    subcategory: str = Query(""),
    q: Annotated[str, Query(max_length=1000)] = "",
):
    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"].isoformat(),
            "score": sum(r["score"] for r in row["results"])
            / max(len(row["results"]), 1),
        }
        for row in query_result(
            _fetch_chart_rows, scenario, model, eval_type, subcategory, q=q
        )
    ]


@router.get("/facets")
def result_facets(
    eval_type: str = "",
    subcategory: str = "",
    q: Annotated[str, Query(max_length=1000)] = "",
):
    where, params = query_result(
        _build_filters, eval_type=eval_type, subcategory=subcategory, q=q
    )
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"""WITH matching AS (SELECT scenario,test_model FROM eval_results {where})
            SELECT ARRAY(SELECT DISTINCT scenario FROM matching WHERE scenario IS NOT NULL ORDER BY scenario) AS scenarios,
                   ARRAY(SELECT DISTINCT test_model FROM matching WHERE test_model IS NOT NULL ORDER BY test_model) AS models""",
            params,
        )
        return dict(cur.fetchone())


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
            cur.execute(
                "DELETE FROM eval_results WHERE id = %s RETURNING id", (eval_id,)
            )
            row = cur.fetchone()

    require_found(row, "Eval", eval_id)
    return delete_response(eval_id)
