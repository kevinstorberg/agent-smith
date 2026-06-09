from collections.abc import Mapping
from typing import Any

from fastapi import WebSocket


class WebSocketMessageHandler:
    """Default message protocol for the Agent Smith WebSocket route."""

    async def handle(self, websocket: WebSocket, message: Mapping[str, Any]) -> None:
        await websocket.send_json(self.response_for(message))

    def response_for(self, message: Mapping[str, Any]) -> dict[str, Any]:
        if message.get("type") == "ping":
            return {"type": "pong"}
        return dict(message)
