from __future__ import annotations

from services.config import ALL_AGENTS, MCP_BASE

MCP_SERVERS = [
    ("memory", f"{MCP_BASE}/mcp/memory/", "Store and search observations, learnings, and context"),
    ("plans", f"{MCP_BASE}/mcp/plans/", "Save and retrieve implementation plans and strategies"),
    ("harness", f"{MCP_BASE}/mcp/harness/", "Manage rules, skills, tools, hooks, and agents"),
    ("evals", f"{MCP_BASE}/mcp/evals/", "Manage evaluation suites and scenarios"),
    ("graphs", f"{MCP_BASE}/mcp/graphs/", "Run hardcoded LangGraph workflows by type"),
]


def seed_mcp_servers() -> None:
    from services.api.models.tool import get_tool
    from services.api.models.shared.harness import create_item

    for name, url, description in MCP_SERVERS:
        if get_tool(name):
            continue
        create_item(
            "tool", name,
            content={"body": "", "metadata": {"url": url, "description": description}},
            agents=ALL_AGENTS,
        )


def seed_all() -> None:
    seed_mcp_servers()
