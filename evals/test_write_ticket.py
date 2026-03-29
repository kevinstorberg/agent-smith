from __future__ import annotations

import pytest

from evals.shared.runner import run_agent
from evals.shared.judge import evaluate
from evals.shared.results import save_eval_result

_db_initialized = False


def _ensure_db():
    global _db_initialized
    if not _db_initialized:
        from scripts.shared.paths import bootstrap
        bootstrap()
        from services.db import init_db
        init_db()
        _db_initialized = True


def load_scenarios() -> list[dict]:
    _ensure_db()
    from services.db.evals import list_enabled_scenarios_for_suite
    return list_enabled_scenarios_for_suite("skills_write_ticket")


def scenario_ids(scenarios):
    return [s["name"] for s in scenarios]


@pytest.mark.parametrize("scenario", load_scenarios(), ids=scenario_ids(load_scenarios()))
def test_write_ticket_compliance(scenario, eval_config):
    from services.db.evals import resolve_items, resolve_extra_context

    model = eval_config["model"]
    extra_ctx = resolve_extra_context(scenario["items"])
    output = run_agent(model, scenario["prompt"], extra_context=extra_ctx)

    items = resolve_items(scenario["items"])
    assert items, "No items to evaluate against."

    all_results = []
    for item_name, item_content in items:
        result = evaluate(
            scenario["prompt"], output,
            threshold=eval_config["threshold"],
            judge_prompt=scenario["judge_prompt"],
            rule_name=item_name,
            rule_content=item_content,
        )
        all_results.append(result)

    save_eval_result(
        scenario["eval_type"], scenario["name"], model,
        eval_config["judge_model"], eval_config["threshold"],
        output, all_results,
        subcategory=scenario["subcategory"],
        prompt=scenario["prompt"],
        eval_suite_id=scenario["suite_id"],
        eval_scenario_id=scenario["id"],
    )

    for r in all_results:
        assert r["score"] >= eval_config["threshold"], (
            f"{r['rule']}: scored {r['score']}: {r['reason']}"
        )
