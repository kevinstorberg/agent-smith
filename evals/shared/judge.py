from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "gpt-5.4")
JUDGE_CONFIG_PATH = Path(__file__).parent.parent / "config" / "rules" / "judge.yaml"

_judge_configs: dict[str, dict] = {}


def _load_judge_config(config_path: str | None = None) -> dict:
    path = config_path or str(JUDGE_CONFIG_PATH)
    if path not in _judge_configs:
        _judge_configs[path] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return _judge_configs[path]


def _rule_to_steps(rule_content: str) -> list[str]:
    steps = []
    for match in re.finditer(r"^\s*\d+\.\s+(.+)", rule_content, re.MULTILINE):
        statement = match.group(1).rstrip(".")
        steps.append(f"Does the output demonstrate: {statement}?")
    return steps


def evaluate(
    input: str,
    output: str,
    rule_path: str,
    threshold: float,
    judge_config_path: str | None = None,
) -> dict:
    rule_name = Path(rule_path).stem
    rule_content = Path(rule_path).read_text(encoding="utf-8")
    config = _load_judge_config(judge_config_path)

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
