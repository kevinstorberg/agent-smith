from __future__ import annotations

import asyncio
from datetime import datetime

from db.unit_of_work import unit_of_work
from src.agent_smith.services.evals import EvalService


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
    eval_suite_id: int | None = None,
    eval_scenario_id: int | None = None,
) -> int:
    async def _save() -> int:
        async with unit_of_work() as uow:
            return await EvalService().save_result(
                uow,
                timestamp=timestamp,
                eval_type=eval_type,
                scenario=scenario,
                test_model=test_model,
                judge_model=judge_model,
                threshold=threshold,
                output=output,
                results=results,
                subcategory=subcategory,
                prompt=prompt,
                eval_suite_id=eval_suite_id,
                eval_scenario_id=eval_scenario_id,
            )

    return asyncio.run(_save())
