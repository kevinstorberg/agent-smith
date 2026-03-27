from __future__ import annotations

from glob import glob
from pathlib import Path

import pytest
import yaml

from evals.shared.runner import run_agent
from evals.shared.judge import evaluate
from evals.shared.results import save_eval_result

SCENARIOS_PATH = Path(__file__).parent / "config" / "write_ticket" / "scenarios.yaml"
CRITERIA_DIR = Path(__file__).parent / "config" / "write_ticket" / "criteria"
JUDGE_CONFIG_PATH = str(Path(__file__).parent / "config" / "write_ticket" / "judge.yaml")


def _load_skill_content() -> str:
    from services.db.harness import get_skill
    skill = get_skill("write_ticket")
    assert skill, "write_ticket skill not found in harness DB"
    return skill["content"]["body"]


def load_scenarios() -> list[dict]:
    all_scenarios = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))["scenarios"]
    return [s for s in all_scenarios if s.get("enabled", True)]


def scenario_ids(scenarios):
    return [s["name"] for s in scenarios]


@pytest.mark.parametrize("scenario", load_scenarios(), ids=scenario_ids(load_scenarios()))
def test_write_ticket_compliance(scenario, eval_config):
    model = eval_config["model"]
    skill_content = _load_skill_content()
    output = run_agent(model, scenario["prompt"], extra_context=skill_content)

    criteria_files = sorted(glob(str(CRITERIA_DIR / "*.md")))
    assert criteria_files, f"No criteria files found in {CRITERIA_DIR}"

    all_results = []
    for criteria_path in criteria_files:
        result = evaluate(
            scenario["prompt"], output, criteria_path,
            eval_config["threshold"],
            judge_config_path=JUDGE_CONFIG_PATH,
        )
        all_results.append(result)

    save_eval_result(
        "skills", scenario["name"], model,
        eval_config["judge_model"], eval_config["threshold"],
        output, all_results,
        subcategory="write_ticket",
    )

    for r in all_results:
        assert r["score"] >= eval_config["threshold"], (
            f"{r['rule']}: scored {r['score']}: {r['reason']}"
        )
