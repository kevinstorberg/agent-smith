from __future__ import annotations

from pathlib import Path

import pytest

from evals.test_rules import load_scenarios, EXCLUDE_RULES, RULES_DIR
from evals.shared.runner import run_agent


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
