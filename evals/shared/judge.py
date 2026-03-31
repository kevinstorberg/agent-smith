from __future__ import annotations

import os
import re
from pathlib import Path

from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "gpt-5.4")


def _strip_code_blocks(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"```.*", "", text, flags=re.DOTALL)
    return text


def _rule_to_steps(rule_content: str) -> list[str]:
    stripped = _strip_code_blocks(rule_content)
    steps = []
    for match in re.finditer(r"^\s*\d+\.\s+(.+)", stripped, re.MULTILINE):
        statement = match.group(1).rstrip(".")
        steps.append(f"Does the output demonstrate: {statement}?")
    return steps


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
