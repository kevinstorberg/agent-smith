from __future__ import annotations

from glob import glob
from pathlib import Path

import pytest
import yaml

from evals.shared.runner import run_agent
from evals.shared.judge import evaluate
from evals.shared.results import save_eval_result

REPO_ROOT = Path(__file__).parent.parent
SCENARIOS_PATH = Path(__file__).parent / "config" / "rules" / "scenarios.yaml"
RULES_DIR = REPO_ROOT / "harness" / "rules" / "shared"
EXCLUDE_RULES = {"memory"}


def load_scenarios() -> list[dict]:
    all_scenarios = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))["scenarios"]
    return [s for s in all_scenarios if s.get("enabled", True)]


def scenario_ids(scenarios):
    return [s["name"] for s in scenarios]


@pytest.mark.parametrize("scenario", load_scenarios(), ids=scenario_ids(load_scenarios()))
def test_rules_compliance(scenario, eval_config):
    model = eval_config["model"]
    output = run_agent(model, scenario["prompt"])

    rule_files = [
        r for r in sorted(glob(str(RULES_DIR / "*.md")))
        if Path(r).stem not in EXCLUDE_RULES
    ]
    assert rule_files, f"No rule files found in {RULES_DIR}"

    all_results = []
    for rule_path in rule_files:
        result = evaluate(scenario["prompt"], output, rule_path, eval_config["threshold"])
        all_results.append(result)

    save_eval_result(
        "rules", scenario["name"], model,
        eval_config["judge_model"], eval_config["threshold"],
        output, all_results,
        subcategory="plans",
        prompt=scenario["prompt"],
    )

    for r in all_results:
        assert r["score"] >= eval_config["threshold"], (
            f"{r['rule']}: scored {r['score']}: {r['reason']}"
        )
