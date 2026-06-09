import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.api.errors import APIException
from src.graphs.base import GraphRuntime, build_graph_runtime

GraphRuntimeBuilder = Callable[..., GraphRuntime]


class GraphRunRequest(BaseModel):
    state: dict[str, Any] = Field(default_factory=dict)
    thread_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("thread_id")
    @classmethod
    def validate_thread_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("thread_id must be non-empty when provided")
        return value


def create_graph_router(
    *,
    graph_builder: GraphRuntimeBuilder = build_graph_runtime,
    prefix: str = "/graphs",
    tags: list[str] | None = None,
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=tags or ["graphs"])

    @router.post("/{graph_name}/invoke")
    async def invoke_graph(graph_name: str, payload: GraphRunRequest):
        runtime = _build_runtime(graph_builder, graph_name, payload.context)
        try:
            result = await runtime.ainvoke(payload.state, thread_id=payload.thread_id)
        except Exception as exc:
            raise _runtime_error(exc) from exc
        return jsonable_encoder(result)

    @router.post("/{graph_name}/stream")
    async def stream_graph(graph_name: str, payload: GraphRunRequest):
        runtime = _build_runtime(graph_builder, graph_name, payload.context)
        return StreamingResponse(
            _stream_events(runtime, payload),
            media_type="text/event-stream",
        )

    return router


def _build_runtime(graph_builder: GraphRuntimeBuilder, graph_name: str, context: dict[str, Any]) -> GraphRuntime:
    try:
        return graph_builder(graph_name, scope=context)
    except APIException:
        raise
    except ValueError as exc:
        raise APIException(status_code=400, code="graph_configuration_error", message=str(exc)) from exc


async def _stream_events(runtime: GraphRuntime, payload: GraphRunRequest) -> AsyncIterator[str]:
    try:
        async for event in runtime.astream_events(payload.state, thread_id=payload.thread_id):
            yield _sse("graph_event", event)
    except Exception:
        yield _sse(
            "error",
            {
                "error": {
                    "code": "graph_runtime_error",
                    "message": "Graph execution failed",
                }
            },
        )


def _runtime_error(exc: Exception) -> APIException:
    if isinstance(exc, APIException):
        return exc
    return APIException(status_code=500, code="graph_runtime_error", message="Graph execution failed")


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), default=str)}\n\n"
