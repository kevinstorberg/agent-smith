import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from config.loader import GraphConfigNotFound
from src.api.errors import RequestIDMiddleware, register_error_handlers
from src.graphs.endpoints import create_graph_router


@pytest.mark.integration
async def test_graph_invoke_endpoint_returns_final_state_and_passes_context():
    calls = {}
    runtime = FakeGraphRuntime(result={"answer": "done"})

    def graph_builder(graph_name, *, scope):
        calls["graph_name"] = graph_name
        calls["scope"] = scope
        return runtime

    client = create_client(graph_builder)

    async with client:
        response = await client.post(
            "/graphs/workflow/invoke",
            json={
                "state": {"messages": [{"role": "user", "content": "hello"}]},
                "thread_id": "thread-1",
                "context": {"request_id": "request-1"},
            },
        )

    assert response.status_code == 200
    assert response.json() == {"answer": "done"}
    assert calls == {"graph_name": "workflow", "scope": {"request_id": "request-1"}}
    assert runtime.invocations == [({"messages": [{"role": "user", "content": "hello"}]}, "thread-1")]


@pytest.mark.integration
async def test_graph_stream_endpoint_emits_sse_events():
    runtime = FakeGraphRuntime(events=[{"type": "token", "content": "hello"}])
    client = create_client(lambda graph_name, *, scope: runtime)

    async with client:
        response = await client.post("/graphs/workflow/stream", json={"state": {"messages": []}})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'event: graph_event\ndata: {"type": "token", "content": "hello"}' in response.text


@pytest.mark.integration
async def test_graph_endpoint_invalid_body_uses_error_envelope():
    client = create_client(lambda graph_name, *, scope: FakeGraphRuntime())

    async with client:
        response = await client.post("/graphs/workflow/invoke", json={"state": []})

    error = response.json()["error"]
    assert response.status_code == 422
    assert error["code"] == "validation_error"
    assert error["request_id"]


@pytest.mark.integration
async def test_graph_endpoint_blank_thread_id_uses_error_envelope():
    client = create_client(lambda graph_name, *, scope: FakeGraphRuntime())

    async with client:
        response = await client.post("/graphs/workflow/invoke", json={"thread_id": "   "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.integration
async def test_graph_builder_value_error_uses_configuration_error_envelope():
    def graph_builder(graph_name, *, scope):
        raise ValueError("Unknown graph runtime kind: 'custom'")

    client = create_client(graph_builder)

    async with client:
        response = await client.post("/graphs/workflow/invoke", json={"state": {}})

    error = response.json()["error"]
    assert response.status_code == 400
    assert error["code"] == "graph_configuration_error"
    assert error["message"] == "Unknown graph runtime kind: 'custom'"


@pytest.mark.integration
async def test_missing_graph_config_uses_configuration_error_envelope():
    def graph_builder(graph_name, *, scope):
        raise GraphConfigNotFound(f"Graph config not found: config/graphs/{graph_name}.yaml")

    client = create_client(graph_builder)

    async with client:
        response = await client.post("/graphs/missing/invoke", json={"state": {}})

    error = response.json()["error"]
    assert response.status_code == 400
    assert error["code"] == "graph_configuration_error"
    assert "config/graphs/missing.yaml" in error["message"]


@pytest.mark.integration
async def test_graph_runtime_exception_uses_error_envelope():
    runtime = FakeGraphRuntime(invoke_error=RuntimeError("provider failed"))
    client = create_client(lambda graph_name, *, scope: runtime)

    async with client:
        response = await client.post("/graphs/workflow/invoke", json={"state": {}})

    error = response.json()["error"]
    assert response.status_code == 500
    assert error["code"] == "graph_runtime_error"
    assert error["message"] == "Graph execution failed"
    assert "provider failed" not in response.text


@pytest.mark.integration
async def test_graph_stream_runtime_exception_emits_error_event():
    runtime = FakeGraphRuntime(events=[{"type": "start"}], stream_error=RuntimeError("provider failed"))
    client = create_client(lambda graph_name, *, scope: runtime)

    async with client:
        response = await client.post("/graphs/workflow/stream", json={"state": {}})

    assert response.status_code == 200
    assert 'event: graph_event\ndata: {"type": "start"}' in response.text
    assert (
        'event: error\ndata: {"error": {"code": "graph_runtime_error", "message": "Graph execution failed"}}'
        in response.text
    )


def create_client(graph_builder):
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(RequestIDMiddleware)
    app.include_router(create_graph_router(graph_builder=graph_builder))
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test")


class FakeGraphRuntime:
    def __init__(self, *, result=None, events=None, invoke_error=None, stream_error=None):
        self.result = result or {}
        self.events = events or []
        self.invoke_error = invoke_error
        self.stream_error = stream_error
        self.invocations = []

    async def ainvoke(self, state, *, thread_id=None):
        if self.invoke_error:
            raise self.invoke_error
        self.invocations.append((state, thread_id))
        return self.result

    async def astream_events(self, state, *, thread_id=None):
        for event in self.events:
            yield event
        if self.stream_error:
            raise self.stream_error
