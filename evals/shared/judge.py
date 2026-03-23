from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "gpt-5.4")
JUDGE_CONFIG_PATH = Path(__file__).parent.parent / "config" / "rules" / "judge.yaml"

_judge_config = None


def _load_judge_config() -> dict:
    global _judge_config
    if _judge_config is None:
        _judge_config = yaml.safe_load(JUDGE_CONFIG_PATH.read_text(encoding="utf-8"))
    return _judge_config


def _rule_to_steps(rule_content: str) -> list[str]:
    steps = []
    for match in re.finditer(r"^\s*\d+\.\s+(.+)", rule_content, re.MULTILINE):
        statement = match.group(1).rstrip(".")
        steps.append(f"Does the output demonstrate: {statement}?")
    return steps


def evaluate(input: str, output: str, rule_path: str, threshold: float) -> dict:
    rule_name = Path(rule_path).stem
    rule_content = Path(rule_path).read_text(encoding="utf-8")
    config = _load_judge_config()

    steps = _rule_to_steps(rule_content)
    criteria = f"{config['prompt']}\n\nRule:\n{rule_content}"

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
