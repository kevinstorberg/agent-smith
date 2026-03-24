from __future__ import annotations

from datetime import datetime, timezone

from evals.shared.db import save_result


def save_eval_result(
    eval_type: str,
    scenario_name: str,
    model: str,
    judge_model: str,
    threshold: float,
    output: str,
    results: list[dict],
) -> int:
    return save_result(
        timestamp=datetime.now(timezone.utc),
        eval_type=eval_type,
        scenario=scenario_name,
        test_model=model,
        judge_model=judge_model,
        threshold=threshold,
        output=output,
        results=results,
    )
