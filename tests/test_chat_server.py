from __future__ import annotations

import asyncio

from services.chat.server import mcp


def test_chat_server_exposes_only_agent_tools():
    tools = asyncio.run(mcp.list_tools())

    assert [tool.name for tool in tools] == ["chat_read", "chat_post"]
    assert "create" not in " ".join(tool.name for tool in tools)
    assert "stop" not in " ".join(tool.name for tool in tools)
