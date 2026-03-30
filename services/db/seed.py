from __future__ import annotations

import os
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ALL_AGENTS = ["claude", "codex", "gemini"]


def _mcp_url() -> str:
    port = os.environ.get("DASHBOARD_PORT", "7654")
    return f"http://localhost:{port}/mcp/"


def seed_memory_tool() -> None:
    """Seed the memory MCP tool if it doesn't already exist."""
    from services.db.harness import get_tool, create_item

    if get_tool("memory"):
        return

    create_item(
        "tool", "memory",
        content={"body": "", "metadata": {"url": _mcp_url(), "description": "Vector memory with semantic search"}},
        agents=ALL_AGENTS,
    )


def seed_plan_tools() -> None:
    """Seed the plan_save and plan_get MCP tools if they don't already exist."""
    from services.db.harness import get_tool, create_item

    tools = [
        ("plan_save", "Save a finalized plan to the database"),
        ("plan_get", "Retrieve a plan by ID or fuzzy search"),
    ]
    for name, desc in tools:
        if get_tool(name):
            continue
        create_item(
            "tool", name,
            content={"body": "", "metadata": {"url": _mcp_url(), "description": desc}},
            agents=ALL_AGENTS,
        )


def seed_rule_evals() -> None:
    """Seed the rules/plans eval suite and its scenarios if the suite doesn't exist."""
    from services.db.evals import get_suite_by_name, create_suite, create_scenario

    if get_suite_by_name("rules_plans"):
        return

    evals_config = REPO_ROOT / "evals" / "config" / "rules"
    judge_path = evals_config / "judge.yaml"
    scenarios_path = evals_config / "scenarios.yaml"

    assert judge_path.exists(), f"Judge config not found: {judge_path}"
    assert scenarios_path.exists(), f"Scenarios not found: {scenarios_path}"

    judge_data = yaml.safe_load(judge_path.read_text(encoding="utf-8"))
    assert "prompt" in judge_data, f"No 'prompt' key in {judge_path}"

    suite_id = create_suite(
        name="rules_plans",
        eval_type="rules",
        subcategory="plans",
        judge_prompt=judge_data["prompt"],
        items={"source": "harness", "harness_type": "rule", "agent": "claude", "exclude": ["memory"]},
    )

    scenarios_data = yaml.safe_load(scenarios_path.read_text(encoding="utf-8"))
    for sc in scenarios_data.get("scenarios", []):
        create_scenario(
            suite_id=suite_id,
            name=sc["name"],
            prompt=sc["prompt"],
            enabled=sc.get("enabled", True),
        )


def seed_all() -> None:
    """Run all seeders. Safe for existing databases — only inserts missing data."""
    seed_memory_tool()
    seed_plan_tools()
    seed_rule_evals()
