from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402

bootstrap()

from mcp.server.fastmcp import FastMCP  # noqa: E402

from services.chat.service import post_agent_message, read_agent_room  # noqa: E402

mcp = FastMCP("chat - shared rooms for coding agents")


@mcp.tool()
async def chat_read(
    room_id: int,
    after_message_id: int = 0,
    wait_seconds: int = 0,
) -> dict:
    """Read new messages from a Chat Room, optionally waiting up to 20 seconds.

    Keep the returned last_message_id as the next after_message_id. A closed
    outcome is terminal: stop reading and posting. A timeout is expected and
    means no one posted during this bounded wait.
    """
    return await read_agent_room(room_id, after_message_id, wait_seconds)


@mcp.tool()
def chat_post(room_id: int, agent: str, body: str) -> dict:
    """Post one message as the calling coding agent.

    agent must name the actual calling client (claude, codex, or gemini). Never
    impersonate another agent. Posting fails after the User stops agent access.
    """
    return post_agent_message(room_id, agent, body)
