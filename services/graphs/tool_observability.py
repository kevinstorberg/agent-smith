from __future__ import annotations

from contextlib import contextmanager

from langchain.agents.middleware import AgentMiddleware

from scripts.shared.operation_logging import agent_action
from scripts.shared.tool_logging import ToolInvocation
from services.observability import action_operation, trigger_context


class ActionLoggingMiddleware(AgentMiddleware):
    def __init__(self, agent_name: str = "unknown"):
        self.agent_name = agent_name

    @contextmanager
    def _tool_scope(self, request):
        name = request.tool.name if request.tool is not None else "unknown"
        resource, action = agent_action(name)
        invocation = ToolInvocation.capture(
            agent=self.agent_name,
            tool=request.tool_call.get("name", name),
            arguments=request.tool_call.get("args", {}),
        )
        with (
            trigger_context(agent_tool=invocation.tool),
            action_operation(
                resource, action, owner="agent_tool", invocation=invocation
            ),
        ):
            yield

    def wrap_tool_call(self, request, handler):
        with self._tool_scope(request):
            return handler(request)

    async def awrap_tool_call(self, request, handler):
        with self._tool_scope(request):
            return await handler(request)
