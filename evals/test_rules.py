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
EXCLUDE_RULES = {"memory"}


def load_scenarios() -> list[dict]:
    all_scenarios = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))["scenarios"]
    return [s for s in all_scenarios if s.get("enabled", True)]


def scenario_ids(scenarios):
    return [s["name"] for s in scenarios]


@pytest.mark.parametrize("scenario", load_scenarios(), ids=scenario_ids(load_scenarios()))
def test_rules_compliance(scenario, eval_config, results_dir):
    output = run_agent(eval_config["model"], scenario["prompt"])

    ts = datetime.now(timezone.utc)
    ts_str = ts.strftime("%Y%m%d_%H%M%S")
    output_file = results_dir / f"{eval_config['model']}_{scenario['name']}_{ts_str}.txt"
    output_file.write_text(output, encoding="utf-8")

    rule_files = [
        r for r in sorted(glob(str(RULES_DIR / "*.md")))
        if Path(r).stem not in EXCLUDE_RULES
    ]
    assert rule_files, f"No rule files found in {RULES_DIR}"

    all_results = []
    for rule_path in rule_files:
        result = evaluate(scenario["prompt"], output, rule_path, eval_config["threshold"])
        all_results.append(result)

    results_file = results_dir / f"{eval_config['model']}_{scenario['name']}_{ts_str}_eval.json"
    results_file.write_text(
        json.dumps({
            "scenario": scenario["name"],
            "model": eval_config["model"],
            "judge_model": eval_config["judge_model"],
            "timestamp": ts.isoformat(),
            "results": all_results,
        }, indent=2),
        encoding="utf-8",
    )

    for r in all_results:
        assert r["score"] >= eval_config["threshold"], (
            f"{r['rule']}: scored {r['score']}: {r['reason']}"
        )
