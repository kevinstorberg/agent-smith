from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from scripts.shared.operation_logging import KNOWN_GRAPHS, tool_action
from scripts.shared.tool_logging import ToolInvocation
from services.observability import action_operation, current_trigger, trigger_context


class _ReplacedRequestNoise(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not (
            record.levelno == logging.INFO
            and record.msg == "Processing request of type %s"
        )


logging.getLogger("mcp.server.lowlevel.server").addFilter(_ReplacedRequestNoise())


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
        parameters = arguments if arguments is not None else {}
        client = self._client_name()
        invocation = ToolInvocation.capture(
            agent=client, tool=name, arguments=parameters
        )
        registered = self._tool_manager.get_tool(name)
        namespace = self.name.split(" - ")[0]
        resource, action = tool_action(
            namespace, name if registered is not None else "unknown"
        )
        fields = {}
        if namespace == "graphs" and name == "run_graph":
            graph = parameters.get("type")
            fields["graph"] = (
                graph if isinstance(graph, str) and graph in KNOWN_GRAPHS else "unknown"
            )
        with (
            trigger_context(
                trigger="mcp",
                source=namespace,
                tool=name if registered is not None else "unknown",
                client=invocation.agent,
                request_id=current_trigger().get("request_id") or str(uuid4()),
                reason="mcp_tool",
                **fields,
            ),
            action_operation(resource, action, owner="mcp", invocation=invocation),
        ):
            return await self._invoke_tool(name, parameters)

    async def _invoke_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return await super().call_tool(name, arguments)
