from __future__ import annotations

from contextlib import contextmanager

from langchain.agents.middleware import AgentMiddleware

from scripts.shared.operation_logging import agent_action
from services.observability import action_operation, trigger_context


class ActionLoggingMiddleware(AgentMiddleware):
    @contextmanager
    def _tool_scope(self, request):
        name = request.tool.name if request.tool is not None else "unknown"
        resource, action = agent_action(name)
        with (
            trigger_context(agent_tool=name),
            action_operation(resource, action, owner="agent_tool"),
        ):
            yield

    def wrap_tool_call(self, request, handler):
        with self._tool_scope(request):
            return handler(request)

    async def awrap_tool_call(self, request, handler):
        with self._tool_scope(request):
            return await handler(request)
