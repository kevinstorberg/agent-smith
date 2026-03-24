from __future__ import annotations

from pathlib import Path

import pytest

from evals.test_rules import load_scenarios, EXCLUDE_RULES, RULES_DIR
from evals.shared.runner import run_agent
from evals.shared.judge import _rule_to_steps, _load_judge_config


def _postgres_available() -> bool:
    try:
        import psycopg2
        conn = psycopg2.connect("postgresql://localhost/agent_smith")
        conn.close()
        return True
    except Exception:
        return False


def test_load_scenarios_filters_disabled():
    scenarios = load_scenarios()
    for s in scenarios:
        assert s.get("enabled", True) is True


def test_load_scenarios_returns_nonempty():
    assert len(load_scenarios()) > 0


def test_run_agent_rejects_unknown_model():
    with pytest.raises(ValueError):
        run_agent("unknown-model-xyz", "hello")


def test_exclude_rules_filters_memory():
    from glob import glob
    rule_files = [
        Path(r).stem for r in sorted(glob(str(RULES_DIR / "*.md")))
        if Path(r).stem not in EXCLUDE_RULES
    ]
    assert "memory" not in rule_files
    assert len(rule_files) > 0


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
    not _postgres_available(),
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
    )
    assert run_id > 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT scenario, test_model FROM eval_results WHERE id = %s", (run_id,))
            row = cur.fetchone()
            assert row == ("test_scenario", "test-model")

            cur.execute("DELETE FROM eval_results WHERE id = %s", (run_id,))

