from __future__ import annotations

import os

from scripts.shared.agents import AGENT_TARGETS

ALL_AGENTS: list[str] = list(AGENT_TARGETS)
DASHBOARD_PORT: str = os.environ.get("DASHBOARD_PORT", "7654")
MCP_URL: str = f"http://localhost:{DASHBOARD_PORT}/mcp/"
