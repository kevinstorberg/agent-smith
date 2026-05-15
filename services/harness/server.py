from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from mcp.server.fastmcp import FastMCP  # noqa: E402
from scripts.shared.validation import empty_to_none  # noqa: E402

from services.api.models.shared.harness import (  # noqa: E402
    VALID_TABLES, list_items, get_item, upsert_item,
)
from services.api.models.harness_config import list_configs, update_config  # noqa: E402

mcp = FastMCP("harness - manage rules, skills, tools, hooks, and agents")


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
def harness_sync_item(
    item_type: str,
    item_id: int = 0,
    name: str = "",
    project: str = "",
) -> str:
    """
    Sync a single harness item to disk by ID or name.

    Args:
        item_type: Type of item (rule, skill, tool, hook, agent).
        item_id:   Database ID (use 0 to lookup by name).
        name:      Item name (used if item_id=0).
        project:   Project scope for name lookup (empty = shared).

    Returns:
        Success message or error.
    """
    assert item_type in VALID_TABLES, f"item_type must be one of {VALID_TABLES}"

    if item_id == 0:
        if not name:
            return "Error: Must provide either item_id or name"
        item = get_item(item_type, name, project=empty_to_none(project))
        if not item:
            return f"Not found: {item_type} '{name}'"
        item_id = item["id"]

    from scripts.shared.sync_utils import run_sync_script

    try:
        result = run_sync_script(["--item-type", item_type, "--item-id", str(item_id)])
        if result["success"]:
            return f"Synced {item_type} (id={item_id})\n{result['stdout']}"
        else:
            return f"Sync failed:\n{result['stderr']}"
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Sync failed: {e}"
