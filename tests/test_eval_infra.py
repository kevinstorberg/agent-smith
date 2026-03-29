from __future__ import annotations

from pathlib import Path

import pytest

from evals.shared.judge import _rule_to_steps, _load_judge_config
from tests.conftest import postgres_available

REPO_ROOT = Path(__file__).parent.parent
RULES_DIR = REPO_ROOT / "harness" / "rules" / "shared"
EXCLUDE_RULES = {"memory"}


# --- rules eval infra ---
# TODO: These tests import from evals/test_*.py which triggers DB-backed
# parametrize at import time, breaking CI (no Postgres). Needs a proper
# solution to decouple collection-time DB access from test imports.


# @pytest.mark.skipif(not postgres_available(), reason="Postgres not available")
# def test_load_scenarios_filters_disabled():
#     from evals.test_rules import load_scenarios
#     scenarios = load_scenarios()
#     for s in scenarios:
#         assert s.get("enabled", True) is True


# @pytest.mark.skipif(not postgres_available(), reason="Postgres not available")
# def test_load_scenarios_returns_nonempty():
#     from evals.test_rules import load_scenarios
#     assert len(load_scenarios()) > 0


# @pytest.mark.skipif(not postgres_available(), reason="Postgres not available")
# def test_load_scenarios_have_suite_config():
#     from evals.test_rules import load_scenarios
#     scenarios = load_scenarios()
#     assert len(scenarios) > 0
#     sc = scenarios[0]
#     assert "judge_prompt" in sc
#     assert "items" in sc
#     assert "eval_type" in sc
#     assert "subcategory" in sc
#     assert sc["eval_type"] == "rules"
#     assert sc["subcategory"] == "plans"


# @pytest.mark.skipif(not postgres_available(), reason="Postgres not available")
# def test_run_agent_rejects_unknown_model():
#     from evals.shared.runner import run_agent
#     with pytest.raises(ValueError):
#         run_agent("unknown-model-xyz", "hello")


@pytest.mark.skipif(not postgres_available(), reason="Postgres not available")
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


def test_judge_config_loads():
    config = _load_judge_config()
    assert "prompt" in config
    assert "examples" not in config


def test_rule_files_have_examples():
    for f in sorted(RULES_DIR.glob("*.md")):
        if f.stem in EXCLUDE_RULES:
            continue
        content = f.read_text(encoding="utf-8")
        assert "* **Example" in content, f"{f.stem} should have an example section"


@pytest.mark.skipif(
    not postgres_available(),
    reason="Postgres not available",
)
def test_save_result_inserts_into_db():
    from datetime import datetime, timezone
    from services.db import get_connection, init_db

    init_db()

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


@pytest.mark.skipif(not postgres_available(), reason="Postgres not available")
def test_save_result_with_suite_and_scenario_ids():
    from datetime import datetime, timezone
    from services.db import get_connection, init_db
    from services.db.evals import get_suite_by_name

    init_db()

    suite = get_suite_by_name("rules_plans")
    assert suite, "rules_plans suite must exist (run migrate_evals_to_db.py)"

    from services.db.evals import list_scenarios
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


# --- write_ticket eval infra ---


# @pytest.mark.skipif(not postgres_available(), reason="Postgres not available")
# def test_write_ticket_scenarios_load():
#     from evals.test_write_ticket import load_scenarios as load_wt_scenarios
#     scenarios = load_wt_scenarios()
#     assert len(scenarios) > 0
#     for s in scenarios:
#         assert "name" in s
#         assert "prompt" in s
#         assert "judge_prompt" in s
#         assert s["eval_type"] == "skills"
#         assert s["subcategory"] == "write_ticket"


# --- write_epic eval infra ---


# @pytest.mark.skipif(not postgres_available(), reason="Postgres not available")
# def test_write_epic_scenarios_load():
#     from evals.test_write_epic import load_scenarios as load_we_scenarios
#     scenarios = load_we_scenarios()
#     assert len(scenarios) > 0
#     for s in scenarios:
#         assert "name" in s
#         assert "prompt" in s
#         assert "judge_prompt" in s
#         assert s["eval_type"] == "skills"
#         assert s["subcategory"] == "write_epic"


# --- resolve_items ---


@pytest.mark.skipif(not postgres_available(), reason="Postgres not available")
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


@pytest.mark.skipif(not postgres_available(), reason="Postgres not available")
def test_resolve_extra_context_skill():
    from services.db.evals import resolve_extra_context
    ctx = resolve_extra_context({"source": "skill", "skill_name": "write_ticket"})
    assert ctx is not None
    assert len(ctx) > 0


@pytest.mark.skipif(not postgres_available(), reason="Postgres not available")
def test_resolve_extra_context_harness_is_none():
    from services.db.evals import resolve_extra_context
    ctx = resolve_extra_context({"source": "harness", "harness_type": "rule", "agent": "claude"})
    assert ctx is None
