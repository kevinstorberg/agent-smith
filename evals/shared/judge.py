from __future__ import annotations

import os
from pathlib import Path

from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "gpt-5.4")


def evaluate(input: str, output: str, rule_path: str, threshold: float) -> dict:
    rule_content = Path(rule_path).read_text(encoding="utf-8")
    metric = GEval(
        name=Path(rule_path).stem,
        model=JUDGE_MODEL,
        criteria=(
            f"Given this rule:\n\n{rule_content}\n\n"
            f"Evaluate whether the output follows this rule."
        ),
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=threshold,
    )
    test_case = LLMTestCase(input=input, actual_output=output)
    metric.measure(test_case)
    return {
        "rule": Path(rule_path).stem,
        "score": metric.score,
        "reason": metric.reason,
    }
