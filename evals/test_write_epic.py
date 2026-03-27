from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from evals.shared.runner import run_agent
from evals.shared.judge import evaluate
from evals.shared.results import save_eval_result

SCENARIOS_PATH = Path(__file__).parent / "config" / "write_epic" / "scenarios.yaml"
JUDGE_CONFIG_PATH = str(Path(__file__).parent / "config" / "write_epic" / "judge.yaml")


def _load_skill_content() -> str:
    from services.db.harness import get_skill
    skill = get_skill("write_epic")
    assert skill, "write_epic skill not found in harness DB"
    return skill["content"]["body"]


def load_scenarios() -> list[dict]:
    all_scenarios = yaml.safe_load(SCENARIOS_PATH.read_text(encoding="utf-8"))["scenarios"]
    return [s for s in all_scenarios if s.get("enabled", True)]


def scenario_ids(scenarios):
    return [s["name"] for s in scenarios]


@pytest.mark.parametrize("scenario", load_scenarios(), ids=scenario_ids(load_scenarios()))
def test_write_epic_compliance(scenario, eval_config):
    model = eval_config["model"]
    skill_content = _load_skill_content()
    output = run_agent(model, scenario["prompt"], extra_context=skill_content)

    result = evaluate(
        scenario["prompt"], output,
        threshold=eval_config["threshold"],
        judge_config_path=JUDGE_CONFIG_PATH,
        rule_name="write_epic",
        rule_content=skill_content,
    )

    all_results = [result]

    save_eval_result(
        "skills", scenario["name"], model,
        eval_config["judge_model"], eval_config["threshold"],
        output, all_results,
        subcategory="write_epic",
        prompt=scenario["prompt"],
    )

    assert result["score"] >= eval_config["threshold"], (
        f"{result['rule']}: scored {result['score']}: {result['reason']}"
    )
