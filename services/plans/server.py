from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from mcp.server.fastmcp import FastMCP  # noqa: E402
from scripts.shared.validation import empty_to_none  # noqa: E402

mcp = FastMCP("plans - save and retrieve implementation plans and strategies")


@mcp.tool()
def save(title: str, body: str, project: str = "") -> str:
    """Save an implementation plan or strategy to the database.
    Use this whenever the agent creates a plan, architectural decision, or multi-step approach.
    Always set project to the current repo/project name.

    Args:
        title: Short descriptive title for the plan.
        body: Full plan content (markdown).
        project: The current project/repo name. Always provide this.

    Returns:
        Confirmation with the plan ID.
    """
    from services.api.models.plan import create_plan
    plan_id = create_plan(title, body, project=empty_to_none(project))
    return f"Plan saved (id={plan_id})"


@mcp.tool()
def get(plan_id: int = 0, query: str = "") -> dict | list[dict]:
    """Retrieve a plan by ID or fuzzy search on title.
    Only call when the user explicitly asks to retrieve a plan.

    Args:
        plan_id: Exact plan ID (takes priority over query if > 0).
        query: Fuzzy search term for title (returns up to 5 matches).

    Returns:
        Single plan dict (if plan_id given) or list of matching plans (if query given).
    """
    from services.api.models.plan import get_plan, search_plans
    if plan_id > 0:
        return get_plan(plan_id)
    if query:
        return search_plans(query, limit=5)
    return []
