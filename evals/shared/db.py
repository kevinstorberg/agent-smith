from __future__ import annotations

from datetime import datetime

from psycopg2.extras import Json

from services.db import get_connection

INSERT_SQL = """
INSERT INTO eval_results
    (timestamp, eval_type, subcategory, scenario, test_model, judge_model, threshold, prompt, output, results)
VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""


def save_result(
    timestamp: datetime,
    eval_type: str,
    scenario: str,
    test_model: str,
    judge_model: str,
    threshold: float,
    output: str,
    results: list[dict],
    subcategory: str | None = None,
    prompt: str | None = None,
) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(INSERT_SQL, (
                timestamp,
                eval_type,
                subcategory,
                scenario,
                test_model,
                judge_model,
                threshold,
                prompt,
                Json(output),
                Json(results),
            ))
            return cur.fetchone()[0]
