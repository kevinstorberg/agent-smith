from __future__ import annotations

from evals.shared.judge import evaluate
from evals.shared.results import save_eval_result
from evals.shared.runner import run_agent


def test_compliance(suite_name: str, scenario: dict, eval_config: dict) -> None:
    from services.db.evals import resolve_extra_context, resolve_items

    model = eval_config["model"]
    extra_ctx = resolve_extra_context(scenario["items"])
    output = run_agent(model, scenario["prompt"], extra_context=extra_ctx)

    items = resolve_items(scenario["items"])
    assert items, f"No items to evaluate for scenario '{scenario['name']}' in suite '{suite_name}'."

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
            f"[{suite_name}] {r['rule']}: scored {r['score']}: {r['reason']}"
        )
