from __future__ import annotations

import os
from pathlib import Path

from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from services.rubric import rule_to_eval_steps

JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "gpt-5.4")


def _rule_to_steps(rule_content: str) -> list[str]:
    return rule_to_eval_steps(rule_content)


def evaluate(
    input: str,
    output: str,
    rule_path: str = "",
    threshold: float = 0.0,
    rule_name: str | None = None,
    rule_content: str | None = None,
    judge_prompt: str = "",
) -> dict:
    assert judge_prompt, "judge_prompt is required."
    if rule_content is None:
        assert rule_path, "Either rule_path or rule_content must be provided."
        rule_content = Path(rule_path).read_text(encoding="utf-8")
    if rule_name is None:
        rule_name = Path(rule_path).stem if rule_path else "unnamed"

    steps = _rule_to_steps(rule_content)
    criteria = f"{judge_prompt}\n\nRule:\n{rule_content}"

    metric = GEval(
        name=rule_name,
        model=JUDGE_MODEL,
        criteria=criteria,
        evaluation_steps=steps if steps else None,
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=threshold,
    )
    test_case = LLMTestCase(input=input, actual_output=output)
    metric.measure(test_case)
    return {
        "rule": rule_name,
        "score": metric.score,
        "reason": metric.reason,
    }
