from __future__ import annotations

from pathlib import Path


from evals.shared.judge import _rule_to_steps

REPO_ROOT = Path(__file__).parent.parent
RULES_DIR = REPO_ROOT / "harness" / "rules" / "shared"
EXCLUDE_RULES = {"memory"}


def test_exclude_rules_filters_memory():
    from services.db.harness import collect_rules_from_db
    rule_names = [name for name, _ in collect_rules_from_db("claude") if name not in EXCLUDE_RULES]
    assert "memory" not in rule_names
    assert len(rule_names) > 0


def test_rule_to_steps_extracts_numbered_items():
    content = """## Test Rule
* **Your Process:**
    1. First step here.
    2. Second step with details — and more info.
    3. Third step.
"""
    steps = _rule_to_steps(content)
    assert len(steps) == 3
    assert steps[0].startswith("Does the output demonstrate:")
    assert "First step here" in steps[0]


def test_rule_to_steps_works_on_real_rules():
    for f in sorted(RULES_DIR.glob("*.md")):
        if f.stem in EXCLUDE_RULES:
            continue
        steps = _rule_to_steps(f.read_text(encoding="utf-8"))
        assert len(steps) >= 3, f"{f.stem} should have at least 3 process steps"


def test_rule_files_have_examples():
    for f in sorted(RULES_DIR.glob("*.md")):
        if f.stem in EXCLUDE_RULES:
            continue
        content = f.read_text(encoding="utf-8")
        assert "* **Example" in content, f"{f.stem} should have an example section"


def test_save_result_inserts_into_db():
    from datetime import datetime, timezone
    from services.db import get_connection

    ts = datetime(2099, 1, 1, tzinfo=timezone.utc)
    test_results = [{"rule": "test_rule", "score": 0.95, "reason": "test"}]

    from evals.shared.db import save_result
    run_id = save_result(
        timestamp=ts,
        eval_type="test",
        scenario="test_scenario",
        test_model="test-model",
        judge_model="test-judge",
        threshold=0.8,
        output="test output",
        results=test_results,
        subcategory="test_sub",
    )
    assert run_id > 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT scenario, test_model, subcategory FROM eval_results WHERE id = %s",
                (run_id,),
            )
            row = cur.fetchone()
            assert row == ("test_scenario", "test-model", "test_sub")

            cur.execute("DELETE FROM eval_results WHERE id = %s", (run_id,))


def test_save_result_with_suite_and_scenario_ids():
    from datetime import datetime, timezone
    from services.db import get_connection
    from services.db.evals import get_suite_by_name, list_scenarios

    suite = get_suite_by_name("test_suite")
    assert suite, "test_suite must exist (seeded by conftest)"

    scenarios = list_scenarios(suite["id"])
    assert scenarios, "Suite must have scenarios"
    scenario = scenarios[0]

    from evals.shared.db import save_result
    ts = datetime(2099, 2, 1, tzinfo=timezone.utc)
    run_id = save_result(
        timestamp=ts,
        eval_type="rules",
        scenario=scenario["name"],
        test_model="test-model",
        judge_model="test-judge",
        threshold=0.8,
        output="test output",
        results=[{"rule": "test", "score": 0.9, "reason": "ok"}],
        subcategory="plans",
        eval_suite_id=suite["id"],
        eval_scenario_id=scenario["id"],
    )
    assert run_id > 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT eval_suite_id, eval_scenario_id FROM eval_results WHERE id = %s",
                (run_id,),
            )
            row = cur.fetchone()
            assert row[0] == suite["id"]
            assert row[1] == scenario["id"]

            cur.execute("DELETE FROM eval_results WHERE id = %s", (run_id,))


def test_resolve_items_harness():
    from services.db.evals import resolve_items
    items = resolve_items({
        "source": "harness",
        "harness_type": "rule",
        "agent": "claude",
        "exclude": ["memory"],
    })
    assert len(items) > 0
    names = [n for n, _ in items]
    assert "memory" not in names


def test_resolve_extra_context_harness_is_none():
    from services.db.evals import resolve_extra_context
    ctx = resolve_extra_context({"source": "harness", "harness_type": "rule", "agent": "claude"})
    assert ctx is None
