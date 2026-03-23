from __future__ import annotations

import json
from datetime import datetime, timezone
from glob import glob
from pathlib import Path

import pytest
import yaml

from evals.shared.runner import run_agent
from evals.shared.judge import evaluate

REPO_ROOT = Path(__file__).parent.parent
SCENARIOS_PATH = Path(__file__).parent / "config" / "scenarios.yaml"
RULES_DIR = REPO_ROOT / "harness" / "rules" / "shared"


def load_scenarios() -> list[dict]:
    return yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))["scenarios"]


def scenario_ids(scenarios):
    return [s["name"] for s in scenarios]


@pytest.mark.parametrize("scenario", load_scenarios(), ids=scenario_ids(load_scenarios()))
def test_rules_compliance(scenario, eval_config, results_dir):
    output = run_agent(eval_config["model"], scenario["prompt"])

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_file = results_dir / f"{eval_config['model']}_{scenario['name']}_{timestamp}.txt"
    output_file.write_text(output, encoding="utf-8")

    rule_files = sorted(glob(str(RULES_DIR / "*.md")))
    assert rule_files, f"No rule files found in {RULES_DIR}"

    all_results = []
    for rule_path in rule_files:
        result = evaluate(scenario["prompt"], output, rule_path, eval_config["threshold"])
        all_results.append(result)

    results_file = results_dir / f"{eval_config['model']}_{scenario['name']}_{timestamp}_eval.json"
    results_file.write_text(
        json.dumps({"scenario": scenario["name"], "model": eval_config["model"], "results": all_results}, indent=2),
        encoding="utf-8",
    )

    for r in all_results:
        assert r["score"] >= eval_config["threshold"], (
            f"{r['rule']}: scored {r['score']}: {r['reason']}"
        )
