from __future__ import annotations

from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from services.observability import current_trigger, trigger_context


class ObservedMCP(FastMCP):
    def _client_name(self) -> str:
        try:
            parameters = self.get_context().session.client_params
        except (AttributeError, LookupError, ValueError):
            return "unknown"
        name = getattr(getattr(parameters, "clientInfo", None), "name", None)
        return name if isinstance(name, str) and name.strip() else "unknown"

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> Any:
        registered = self._tool_manager.get_tool(name)
        with trigger_context(
            trigger="mcp",
            source=self.name.split(" - ")[0],
            tool=name if registered is not None else "unknown",
            client=self._client_name(),
            request_id=current_trigger().get("request_id") or str(uuid4()),
            reason="mcp_tool",
        ):
            return await super().call_tool(
                name, arguments if arguments is not None else {}
            )
