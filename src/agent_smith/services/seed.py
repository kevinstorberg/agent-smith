from __future__ import annotations

from db.unit_of_work import unit_of_work
from src.agent_smith.services.harness import HarnessService
from src.settings import get_settings


async def seed_all() -> None:
    settings = get_settings()
    mcp_base = settings.MCP_BASE or f"http://localhost:{settings.DASHBOARD_PORT}"
    async with unit_of_work() as uow:
        await HarnessService().seed_mcp_servers(uow, mcp_base)
