from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("evals - manage evaluation suites and scenarios")


@mcp.tool()
def eval_suite_list(enabled_only: bool = True) -> list[dict]:
    """List eval suites with their scenario counts.

    Args:
        enabled_only: If true, only return enabled suites.

    Returns:
        List of eval suites with id, name, eval_type, subcategory, enabled,
        and scenario_count.
    """
    from services.api.models.evals import list_suites, list_scenarios
    items, _ = list_suites(enabled_only=enabled_only)
    for item in items:
        item["scenario_count"] = len(list_scenarios(item["id"], enabled_only=False))
    return items


@mcp.tool()
def eval_suite_get(name: str = "", suite_id: int = 0) -> dict | None:
    """Get an eval suite by name or ID, including its scenarios.

    Args:
        name:     Suite name (e.g. "rules_plans"). Takes priority if non-empty.
        suite_id: Suite ID (used if name is empty).

    Returns:
        Suite dict with scenarios list, or None if not found.
    """
    from services.api.models.evals import get_suite, get_suite_by_name, list_scenarios
    suite = None
    if name:
        suite = get_suite_by_name(name)
    elif suite_id > 0:
        suite = get_suite(suite_id)
    if suite:
        suite["scenarios"] = list_scenarios(suite["id"], enabled_only=False)
    return suite


@mcp.tool()
def eval_suite_save(
    name: str,
    eval_type: str,
    subcategory: str,
    judge_prompt: str,
    items: dict | None = None,
    config: dict | None = None,
    enabled: bool = True,
) -> str:
    """Create or update an eval suite.

    Args:
        name:         Unique suite name (e.g. "skills_write_ticket").
        eval_type:    Eval type (e.g. "rules", "skills").
        subcategory:  Subcategory (e.g. "plans", "write_ticket").
        judge_prompt: Judge instructions for this suite.
        items:        Items config (source, harness_type/skill_name, exclude).
        config:       Optional overrides (threshold, model, extra_context).
        enabled:      Whether the suite is active.

    Returns:
        Confirmation with the suite ID.
    """
    from services.api.models.evals import upsert_suite
    suite_id = upsert_suite(
        name, eval_type, subcategory, judge_prompt,
        items=items or {}, config=config or {}, enabled=enabled,
    )
    return f"Eval suite saved (id={suite_id})"


@mcp.tool()
def eval_scenario_save(
    suite_name: str,
    name: str,
    prompt: str,
    enabled: bool = True,
) -> str:
    """Create or update a scenario within an eval suite.

    Args:
        suite_name: The parent suite's name (e.g. "rules_plans").
        name:       Scenario name (e.g. "build_a_todo_app").
        prompt:     The scenario prompt text.
        enabled:    Whether the scenario is active.

    Returns:
        Confirmation with the scenario ID.
    """
    from services.api.models.evals import get_suite_by_name, upsert_scenario
    suite = get_suite_by_name(suite_name)
    assert suite, f"Suite not found: {suite_name}"
    scenario_id = upsert_scenario(suite["id"], name, prompt, enabled=enabled)
    return f"Eval scenario saved (id={scenario_id})"
