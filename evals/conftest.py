from __future__ import annotations

import os

import pytest

from scripts.shared.paths import bootstrap
bootstrap(__file__)


def pytest_addoption(parser):
    parser.addoption(
        "--suite",
        action="store",
        default=None,
        help="Eval suite name to run (e.g. rules_plans). Omit to run all enabled suites.",
    )


def pytest_generate_tests(metafunc):
    if "scenario" not in metafunc.fixturenames:
        return

    try:
        from services.api.models.evals import (
            get_suite_by_name,
            list_enabled_scenarios_for_suite,
            list_suites,
        )
    except Exception:
        pytest.skip("Database unavailable")
        return

    suite_filter = metafunc.config.getoption("suite")

    try:
        if suite_filter:
            suite = get_suite_by_name(suite_filter)
            if not suite:
                pytest.fail(f"Suite '{suite_filter}' not found in database")
            suite_names = [suite_filter]
        else:
            suites, _ = list_suites(enabled_only=True)
            suite_names = [s["name"] for s in suites]

        params = []
        ids = []
        for name in suite_names:
            scenarios = list_enabled_scenarios_for_suite(name)
            for s in scenarios:
                params.append((name, s))
                ids.append(f"{name}-{s['name']}")
    except Exception:
        pytest.skip("Database unavailable — skipping eval suite collection")
        return

    if not params:
        pytest.skip("No enabled scenarios found")
        return

    metafunc.parametrize("suite_name,scenario", params, ids=ids)


@pytest.fixture(scope="session")
def eval_config():
    return {
        "model": os.environ.get("EVAL_MODEL", "claude-opus-4-6"),
        "judge_model": os.environ.get("EVAL_JUDGE_MODEL", "gpt-5.4"),
        "threshold": float(os.environ.get("EVAL_THRESHOLD", "0.9")),
    }


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    from services.db import init_db
    init_db()
