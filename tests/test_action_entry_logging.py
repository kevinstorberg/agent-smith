import asyncio
import json
import logging
from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
import pytest

from services import observability
from services.action_items import db
from services.action_items.server import create_server
from services.api.operation_context import request_trigger
from services.api.routers.action_items import router
from services.graphs import agents, runtime
from services.jobs import scheduler
from services.mcp_observability import ObservedMCP
from tests.test_action_items import action_items_empty as action_items_empty
from tests.test_meeting_memory_agent import ScriptedModel, call


SECRET = "PRIVATE_ARGUMENT_RESULT_TOKEN"


@pytest.fixture(autouse=True)
def capture_actions(caplog):
    caplog.set_level(logging.INFO, logger="agent_smith.action")
    caplog.set_level(logging.INFO, logger="agent_smith.billable")


def entries(caplog):
    return [
        r
        for r in caplog.records
        if r.levelno == logging.INFO and hasattr(r, "operation_event")
    ]


@pytest.mark.asyncio
async def test_native_mcp_create_and_read_log_before_database_call_without_payload(
    monkeypatch, caplog
):
    server = create_server()
    original = db.create

    def create(values):
        assert (
            entries(caplog)[-1]
            .getMessage()
            .startswith("ACTION ITEM CREATE [NONBILLABLE]")
        )
        return original(values)

    monkeypatch.setattr(db, "create", create)
    result = await server.call_tool("action_item_create", {"title": SECRET})
    created = result[1] if isinstance(result, tuple) else json.loads(result[0].text)
    await server.call_tool("action_item_get", {"item_id": created["id"]})
    assert [r.getMessage().split(" [", 1)[0] for r in entries(caplog)] == [
        "ACTION ITEM CREATE",
        "ACTION ITEM READ",
    ]
    assert all(r.operation_event["client"] == "unknown" for r in entries(caplog))
    assert SECRET not in caplog.text


def test_native_http_create_logs_template_and_same_action_adapter_only_once(
    monkeypatch, caplog
):
    application = FastAPI(dependencies=[Depends(request_trigger)])
    application.include_router(router, prefix="/api/action-items")
    original = db.create

    def create(values):
        with observability.action_operation("action-items", "create", owner="service"):
            assert len(entries(caplog)) == 1
            return original(values)

    monkeypatch.setattr(db, "create", create)
    with TestClient(application) as client:
        response = client.post("/api/action-items", json={"title": SECRET})
    assert response.status_code == 201 and response.json()["title"] == SECRET
    assert len(entries(caplog)) == 1
    assert entries(caplog)[0].operation_event["source"] == "/api/action-items"
    assert (
        entries(caplog)[0].getMessage().startswith("ACTION ITEM CREATE [NONBILLABLE]")
    )
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_graph_adapter_deduplicates_mcp_but_retains_each_model_attempt(
    monkeypatch, caplog
):
    async def invoke(inputs):
        assert len(entries(caplog)) == 1
        for _ in range(2):
            with observability.billable_operation("bedrock", "chat_completion"):
                pass
        return {"result": inputs["text"]}

    monkeypatch.setattr(
        runtime,
        "scan_library",
        lambda: {
            "opinion": SimpleNamespace(
                INPUT_SCHEMA={"text": "string"},
                build_graph=lambda: SimpleNamespace(ainvoke=invoke),
            ),
        },
    )
    server = ObservedMCP("graphs - test")

    @server.tool()
    async def run_graph(type: str, inputs: dict) -> str:
        return await runtime.dispatch(type, inputs)

    await server.call_tool("run_graph", {"type": "opinion", "inputs": {"text": SECRET}})
    assert entries(caplog)[0].getMessage().startswith("GRAPH RUN [BILLABLE]")
    provider = [
        r
        for r in caplog.records
        if r.levelno == logging.INFO and hasattr(r, "billable_event")
    ]
    assert len(provider) == 2
    assert all(r.getMessage().startswith("MODEL GENERATE [BILLABLE]") for r in provider)
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_native_agent_tool_middleware_logs_before_tool_and_preserves_result(
    monkeypatch, caplog
):
    monkeypatch.setenv("MEMORY_BACKEND", "pinecone")

    @tool("search_memories")
    def search(query: str) -> str:
        """Read prior memories."""
        assert entries(caplog)[0].getMessage().startswith("MEMORY SEARCH [BILLABLE]")
        assert observability.current_trigger()["agent_tool"] == "search_memories"
        with observability.billable_operation("pinecone", "query"):
            return query

    model = ScriptedModel(
        replies=[call("search_memories", query=SECRET), AIMessage(content="finished")]
    )
    monkeypatch.setattr(agents, "build_chat_model", lambda *a, **kw: model)
    agent = agents.create_tool_agent(
        system_prompt="test", model_role="opinion", tools=[search]
    )
    result = await agent.ainvoke({"messages": [HumanMessage(content="test")]})
    assert result["messages"][-1].content == "finished"
    assert result["messages"][-2].content == SECRET
    assert len(entries(caplog)) == 1
    assert observability.current_trigger() == {}
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_unknown_future_tool_is_never_assumed_free(monkeypatch, caplog):
    @tool
    def future_remote_search() -> str:
        """Search a future remote service."""
        return "result"

    model = ScriptedModel(
        replies=[call("future_remote_search"), AIMessage(content="finished")]
    )
    monkeypatch.setattr(agents, "build_chat_model", lambda *a, **kw: model)
    agent = agents.create_tool_agent(
        system_prompt="test", model_role="opinion", tools=[future_remote_search]
    )
    await agent.ainvoke({"messages": [HumanMessage(content="test")]})
    assert (
        entries(caplog)[0]
        .getMessage()
        .startswith("TOOL FUTURE REMOTE SEARCH [BILLABLE?]")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "namespace,name",
    [("action-items", "create"), ("plans", "delete"), ("memory", "search")],
)
async def test_unmapped_mcp_tool_cannot_inherit_local_crud_classification(
    caplog, namespace, name
):
    server = ObservedMCP(namespace + " - test")

    @server.tool(name=name)
    async def future_operation() -> str:
        return "result"

    await server.call_tool(name, {})
    assert len(entries(caplog)) == 1
    assert (
        entries(caplog)[0].getMessage().startswith(f"TOOL {name.upper()} [BILLABLE?]")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_job_entry_precedes_runner_and_does_not_repeat_completion_at_info(
    monkeypatch, caplog, success
):
    monkeypatch.setattr(scheduler, "create_execution", lambda **kwargs: 7)

    async def run(*args):
        assert entries(caplog)[0].getMessage().startswith("JOB RUN [BILLABLE?]")
        assert observability.current_trigger()["execution_id"] == 7
        return {"success": success}

    monkeypatch.setattr(scheduler, "_run_graph_job", run)
    result = await scheduler.execute_job(
        {"id": 3, "input_params": {"graph_type": "echo"}}
    )
    assert result == {"success": success, "execution_id": 7}
    assert len(entries(caplog)) == 1
    assert not [
        r
        for r in caplog.records
        if r.levelno == logging.INFO
        and getattr(r, "work_decision", {}).get("decision") == "job_finished"
    ]
    if not success:
        terminal = [
            r.operation_event
            for r in caplog.records
            if getattr(r, "operation_event", {}).get("phase") == "END"
        ]
        assert terminal[-1]["outcome"] == "failed"


@pytest.mark.asyncio
async def test_concurrent_native_mcp_actions_capture_separate_requests(
    monkeypatch, caplog
):
    server = ObservedMCP("memory - test")
    monkeypatch.setenv("MEMORY_BACKEND", "lancedb")
    barrier = asyncio.Barrier(2)

    @server.tool()
    async def memory_search(query: str) -> str:
        await barrier.wait()
        return query

    await asyncio.gather(
        server.call_tool("memory_search", {"query": SECRET}),
        server.call_tool("memory_search", {"query": SECRET}),
    )
    assert len(entries(caplog)) == 2
    assert len({r.operation_event["request_id"] for r in entries(caplog)}) == 2
    assert all(
        r.getMessage().startswith("MEMORY SEARCH [NONBILLABLE]")
        for r in entries(caplog)
    )
    assert observability.current_trigger() == {}
    assert SECRET not in caplog.text


def test_replaced_sdk_processing_noise_is_narrow_and_preserves_warnings(caplog):
    sdk = logging.getLogger("mcp.server.lowlevel.server")
    caplog.set_level(logging.INFO, logger=sdk.name)
    sdk.info("Processing request of type %s", "CallToolRequest")
    sdk.info("Other SDK diagnostic")
    sdk.warning("Processing request of type %s", "CallToolRequest")
    records = [r for r in caplog.records if r.name == sdk.name]
    assert [r.levelno for r in records] == [logging.INFO, logging.WARNING]
    assert records[0].getMessage() == "Other SDK diagnostic"
