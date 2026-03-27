from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from mcp.server.fastmcp import FastMCP  # noqa: E402

import services.memory.db as db

DEFAULT_PORT = 7367

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
    id = db.add(content=content, repo=repo or None, tags=tags or [])
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
    return db.search(query=query, repo=repo or None, limit=limit)


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
    return db.list_memories(repo=repo or None, limit=limit)


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
        repo=repo or None,
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
    from services.db.plans import create_plan
    plan_id = create_plan(title, body, project=project or None)
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
    from services.db.plans import get_plan, search_plans
    if plan_id > 0:
        return get_plan(plan_id)
    if query:
        return search_plans(query, limit=5)
    return []


import os

if os.environ.get("HARNESS_EDIT_ENABLED", "").lower() == "true":
    from services.db.harness import list_items, get_item, upsert_item

    VALID_TYPES = ("rule", "skill", "tool", "hook")

    @mcp.tool()
    def harness_list(
        item_type: str,
        project: str = "",
        agent: str = "",
    ) -> list[dict]:
        """
        List harness items (rules, skills, tools, or hooks).

        Args:
            item_type: One of "rule", "skill", "tool", "hook".
            project:   Filter to a specific project (empty = shared only).
            agent:     Filter to items assigned to this agent (empty = all).

        Returns:
            List of items with name, content, agents, enabled, version.
        """
        assert item_type in VALID_TYPES, f"item_type must be one of {VALID_TYPES}"
        return list_items(item_type, project=project or None, agent=agent or None)

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
            item_type: One of "rule", "skill", "tool", "hook".
            project:   Project scope (empty = shared).

        Returns:
            The item dict, or None if not found.
        """
        assert item_type in VALID_TYPES, f"item_type must be one of {VALID_TYPES}"
        return get_item(item_type, name, project=project or None)

    @mcp.tool()
    def harness_upsert(
        name: str,
        item_type: str,
        content: dict,
        project: str = "",
        agents: list[str] | None = None,
    ) -> str:
        """
        Create or update a harness item. Bumps version on update.

        Args:
            name:      The item name.
            item_type: One of "rule", "skill", "tool", "hook".
            content:   Dict with "body" (str) and "metadata" (dict) keys.
            project:   Project scope (empty = shared).
            agents:    List of agents to assign (e.g. ["claude", "codex"]).

        Returns:
            Confirmation with the item ID.
        """
        assert item_type in VALID_TYPES, f"item_type must be one of {VALID_TYPES}"
        item_id = upsert_item(
            item_type, name, content,
            project=project or None,
            agents=agents,
        )
        return f"Upserted {item_type} '{name}' (id={item_id})"

    @mcp.tool()
    def harness_disable(
        name: str,
        item_type: str,
        project: str = "",
    ) -> str:
        """
        Disable a harness item (it will be excluded from sync).

        Args:
            name:      The item name.
            item_type: One of "rule", "skill", "tool", "hook".
            project:   Project scope (empty = shared).

        Returns:
            Confirmation message.
        """
        assert item_type in VALID_TYPES, f"item_type must be one of {VALID_TYPES}"
        existing = get_item(item_type, name, project=project or None)
        if not existing:
            return f"Not found: {item_type} '{name}'"
        upsert_item(
            item_type, name, existing["content"],
            project=project or None,
            agents=existing["agents"],
            enabled=False,
        )
        return f"Disabled {item_type} '{name}'"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    mcp.settings.host = "127.0.0.1"
    mcp.settings.port = args.port

    mcp.run(transport="streamable-http")
