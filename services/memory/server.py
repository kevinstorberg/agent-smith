from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from mcp.server.fastmcp import FastMCP  # noqa: E402
from scripts.shared.validation import empty_to_none  # noqa: E402

import services.memory.db as db

mcp = FastMCP("memory")


@mcp.tool()
def memory_add(content: str, repo: str = "", tags: list[str] | None = None) -> str:
    """
    Store a new memory with optional project scope and tags.

    Args:
        content: The text to remember.
        repo:    Project or repo name to scope this memory (e.g. "agent-smith").
        tags:    Short classification labels (e.g. ["auth", "architecture"]).

    Returns:
        The ID of the newly created memory.
    """
    id = db.add(content=content, repo=empty_to_none(repo), tags=tags or [])
    return id


@mcp.tool()
def memory_search(query: str, repo: str = "", limit: int = db.DEFAULT_LIMIT) -> list[dict]:
    """
    Semantically search memories using vector similarity.

    Args:
        query:  Natural language search query.
        repo:   Restrict results to this project/repo (optional).
        limit:  Maximum number of results to return.

    Returns:
        List of matching memories ordered by relevance, each with id, content,
        repo, tags, score, created_at, updated_at.
    """
    return db.search(query=query, repo=empty_to_none(repo), limit=limit)


@mcp.tool()
def memory_list(repo: str = "", limit: int = db.DEFAULT_LIMIT) -> list[dict]:
    """
    List recent memories, newest first.

    Args:
        repo:   Filter to this project/repo (optional).
        limit:  Maximum number of memories to return.

    Returns:
        List of memories with id, content, repo, tags, created_at, updated_at.
    """
    return db.list_memories(repo=empty_to_none(repo), limit=limit)


@mcp.tool()
def memory_delete(id: str) -> str:
    """
    Delete a memory by its ID.

    Args:
        id: The memory ID to delete.

    Returns:
        Confirmation message.
    """
    db.delete(id)
    return f"Deleted: {id}"


@mcp.tool()
def memory_update(
    id: str,
    content: str = "",
    repo: str = "",
    tags: list[str] | None = None,
) -> str:
    """
    Update an existing memory's content, repo, or tags.
    Only the fields you provide will be changed.

    Args:
        id:      The memory ID to update.
        content: New content (re-embeds if changed).
        repo:    New project/repo scope.
        tags:    New tag list.

    Returns:
        Confirmation message.
    """
    db.update(
        id=id,
        content=content or None,
        repo=empty_to_none(repo),
        tags=tags,
    )
    return f"Updated: {id}"


@mcp.tool()
def plan_save(title: str, body: str, project: str = "") -> str:
    """Save a finalized plan to the database.
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
def plan_get(plan_id: int = 0, query: str = "") -> dict | list[dict]:
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


from services.api.models.shared.harness import (
    VALID_TABLES, list_items, get_item, upsert_item,
)
from services.api.models.harness_config import list_configs, update_config


@mcp.tool()
def harness_list(
    item_type: str,
    project: str = "",
    agent: str = "",
) -> list[dict]:
    """
    List harness items (rules, skills, tools, hooks, or agents).

    Args:
        item_type: A valid harness item type (rule, skill, tool, hook, agent).
        project:   Filter to a specific project (empty = shared only).
        agent:     Filter to items assigned to this agent (empty = all).

    Returns:
        List of items with name, content, agents, enabled, version, and configs.
    """
    assert item_type in VALID_TABLES, f"item_type must be one of {VALID_TABLES}"
    rows = list_items(item_type, project=empty_to_none(project), agent=empty_to_none(agent))
    for row in rows:
        row["configs"] = list_configs(row["id"], item_type)
    return rows


@mcp.tool()
def harness_get(
    name: str,
    item_type: str,
    project: str = "",
) -> dict | None:
    """
    Get a single harness item by name and type.

    Args:
        name:      The item name (e.g. "dry", "commit", "Slack").
        item_type: A valid harness item type (rule, skill, tool, hook, agent).
        project:   Project scope (empty = shared).

    Returns:
        The item dict with configs, or None if not found.
    """
    assert item_type in VALID_TABLES, f"item_type must be one of {VALID_TABLES}"
    item = get_item(item_type, name, project=empty_to_none(project))
    if item:
        item["configs"] = list_configs(item["id"], item_type)
    return item


@mcp.tool()
def harness_upsert(
    name: str,
    item_type: str,
    content: dict,
    project: str = "",
    agents: list[str] | None = None,
    device: str = "*",
    repo: str = "*",
) -> str:
    """
    Create or update a harness item. Bumps version on update.
    The device and repo set the default deployment config for new items.

    Args:
        name:      The item name.
        item_type: A valid harness item type (rule, skill, tool, hook, agent).
        content:   Dict with "body" (str) and "metadata" (dict) keys.
        project:   Project scope (empty = shared).
        agents:    List of agents to assign (e.g. ["claude", "codex"]).
        device:    Device scope for default config ("*" = all devices).
        repo:      Repo scope for default config ("*" = global, or absolute path).

    Returns:
        Confirmation with the item ID.
    """
    assert item_type in VALID_TABLES, f"item_type must be one of {VALID_TABLES}"
    item_id = upsert_item(
        item_type, name, content,
        project=empty_to_none(project),
        agents=agents,
    )
    if device != "*" or repo != "*":
        configs = list_configs(item_id, item_type)
        if configs:
            update_config(configs[0]["id"], device=device, repo=repo)
    return f"Upserted {item_type} '{name}' (id={item_id})"


@mcp.tool()
def harness_disable(
    name: str,
    item_type: str,
    project: str = "",
) -> str:
    """
    Disable a harness item by disabling all its config rows.
    The item will be excluded from sync.

    Args:
        name:      The item name.
        item_type: A valid harness item type (rule, skill, tool, hook, agent).
        project:   Project scope (empty = shared).

    Returns:
        Confirmation message.
    """
    assert item_type in VALID_TABLES, f"item_type must be one of {VALID_TABLES}"
    existing = get_item(item_type, name, project=empty_to_none(project))
    if not existing:
        return f"Not found: {item_type} '{name}'"
    configs = list_configs(existing["id"], item_type)
    for cfg in configs:
        update_config(cfg["id"], enabled=False)
    return f"Disabled {item_type} '{name}' ({len(configs)} config(s) disabled)"


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


