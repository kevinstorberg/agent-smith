from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse, ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from services.meetings.analysis import MeetingAnalysisError
from services.meetings.speaker_context import REQUEST_BYTES, encoded_size


class SpeakerRequestGuard(AgentMiddleware):
    def __init__(self, error_class: type[MeetingAnalysisError], revisions: dict[str, int | None],
                 validate_context: Callable[[dict], Awaitable[dict]] | None = None) -> None:
        self.error_class = error_class
        self.revisions = revisions
        self.validate_context = validate_context
        self.diagnostics = {"model_calls": 0, "tool_calls": 0, "tool_names": [], "invalid_tool_calls": 0,
                            "stage_rejections": 0, "finish_reason": "unknown"}

    async def awrap_model_call(self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]) -> ModelResponse:
        messages = [*([request.system_message] if request.system_message else []), *request.messages]
        envelope = {"messages": [message.model_dump() for message in messages],
                    "tools": [convert_to_openai_tool(tool) for tool in request.tools]}
        # Check every turn, including accumulated lookup results and model/tool history.
        if encoded_size(envelope) > REQUEST_BYTES:
            raise self.error_class("Speaker request and tool history exceed the byte budget", error_type="SpeakerRequestTooLarge")
        if self.validate_context:
            current = await self.validate_context(self.revisions)
            if current:
                self.revisions.update(current)
        self.diagnostics["model_calls"] += 1
        response = await handler(request)
        for message in response.result:
            self.diagnostics["invalid_tool_calls"] += len(getattr(message, "invalid_tool_calls", []))
            reason = message.response_metadata.get("finish_reason")
            self.diagnostics["finish_reason"] = reason if reason in {"stop", "length", "tool_calls", "content_filter"} else "unknown"
        return response

    async def awrap_tool_call(self, request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage]]) -> ToolMessage:
        self.diagnostics["tool_calls"] += 1
        name = request.tool_call["name"]
        safe_name = name if name in {"search_known_profiles", "stage_speakers"} else "unknown_tool"
        if safe_name not in self.diagnostics["tool_names"]:
            self.diagnostics["tool_names"].append(safe_name)
        return await handler(request)
