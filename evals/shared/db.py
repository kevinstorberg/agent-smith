from __future__ import annotations

import json
from datetime import datetime, timezone

from psycopg2.extras import Json

from services.db import get_connection

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS eval_results (
    id              SERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    eval_type       TEXT NOT NULL,
    scenario        TEXT NOT NULL,
    test_model      TEXT NOT NULL,
    judge_model     TEXT NOT NULL,
    threshold       REAL NOT NULL,
    output          JSONB NOT NULL,
    results         JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eval_results_timestamp
    ON eval_results(timestamp);
"""

INSERT_SQL = """
INSERT INTO eval_results
    (timestamp, eval_type, scenario, test_model, judge_model, threshold, output, results)
VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""


def init_eval_tables() -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)


def save_result(
    timestamp: datetime,
    eval_type: str,
    scenario: str,
    test_model: str,
    judge_model: str,
    threshold: float,
    output: str,
    results: list[dict],
) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(INSERT_SQL, (
                timestamp,
                eval_type,
                scenario,
                test_model,
                judge_model,
                threshold,
                Json(output),
                Json(results),
            ))
            return cur.fetchone()[0]
