from __future__ import annotations

from services.config import ALL_AGENTS, MCP_URL


def seed_memory_tool() -> None:
    """Seed the memory MCP tool if it doesn't already exist."""
    from services.db.harness import get_tool, create_item

    if get_tool("memory"):
        return

    create_item(
        "tool", "memory",
        content={"body": "", "metadata": {"url": MCP_URL, "description": "Vector memory with semantic search"}},
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
            content={"body": "", "metadata": {"url": MCP_URL, "description": desc}},
            agents=ALL_AGENTS,
        )


def seed_all() -> None:
    """Run all seeders. Safe for existing databases — only inserts missing data."""
    seed_memory_tool()
    seed_plan_tools()
