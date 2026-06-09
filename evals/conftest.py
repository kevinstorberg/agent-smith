from __future__ import annotations

import asyncio
import os

import pytest

from db.unit_of_work import unit_of_work
from src.agent_smith.services.evals import EvalService


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

    suite_filter = metafunc.config.getoption("suite")

    try:
        params, ids = asyncio.run(_collect_eval_params(suite_filter))
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
    return None


async def _collect_eval_params(suite_filter: str | None) -> tuple[list[tuple[str, dict]], list[str]]:
    async with unit_of_work() as uow:
        service = EvalService()
        suites, _ = await service.list_suites(uow, enabled_only=not bool(suite_filter), limit=1000, offset=0)
        if suite_filter:
            suites = [suite for suite in suites if suite["name"] == suite_filter]
            if not suites:
                pytest.fail(f"Suite '{suite_filter}' not found in database")
        params = []
        ids = []
        for suite in suites:
            scenarios = await service.list_scenarios(uow, suite["id"], enabled_only=True)
            for scenario in scenarios:
                params.append((suite["name"], scenario))
                ids.append(f"{suite['name']}-{scenario['name']}")
        return params, ids
