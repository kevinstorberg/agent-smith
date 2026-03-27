from __future__ import annotations

from pathlib import Path

import pytest

from evals.test_rules import load_scenarios, EXCLUDE_RULES, RULES_DIR
from evals.test_write_ticket import (
    load_scenarios as load_wt_scenarios,
    JUDGE_CONFIG_PATH as WT_JUDGE_CONFIG_PATH,
)
from evals.test_write_epic import (
    load_scenarios as load_we_scenarios,
    JUDGE_CONFIG_PATH as WE_JUDGE_CONFIG_PATH,
)
from evals.shared.runner import run_agent
from evals.shared.judge import _rule_to_steps, _load_judge_config
from tests.conftest import postgres_available


def test_load_scenarios_filters_disabled():
    scenarios = load_scenarios()
    for s in scenarios:
        assert s.get("enabled", True) is True


def test_load_scenarios_returns_nonempty():
    assert len(load_scenarios()) > 0


@pytest.mark.skipif(not postgres_available(), reason="Postgres not available")
def test_run_agent_rejects_unknown_model():
    with pytest.raises(ValueError):
        run_agent("unknown-model-xyz", "hello")


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


# --- write_ticket eval infra ---


def test_write_ticket_scenarios_load():
    scenarios = load_wt_scenarios()
    assert len(scenarios) > 0
    for s in scenarios:
        assert s.get("enabled", True) is True
        assert "name" in s
        assert "prompt" in s


def test_write_ticket_judge_config_loads():
    config = _load_judge_config(WT_JUDGE_CONFIG_PATH)
    assert "prompt" in config
    assert len(config["prompt"]) > 50


# --- write_epic eval infra ---


def test_write_epic_scenarios_load():
    scenarios = load_we_scenarios()
    assert len(scenarios) > 0
    for s in scenarios:
        assert s.get("enabled", True) is True
        assert "name" in s
        assert "prompt" in s


def test_write_epic_judge_config_loads():
    config = _load_judge_config(WE_JUDGE_CONFIG_PATH)
    assert "prompt" in config
    assert len(config["prompt"]) > 50

