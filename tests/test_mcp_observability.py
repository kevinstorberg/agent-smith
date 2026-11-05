import asyncio
from contextvars import ContextVar
from types import SimpleNamespace
from uuid import UUID

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from services.graphs import runtime
from services.mcp_observability import ObservedMCP
from services.observability import billable_operation, current_trigger, trigger_context


pytestmark = pytest.mark.usefixtures("terminal_diagnostics")


def billable_records(caplog):
    return [
        record.billable_event
        for record in caplog.records
        if hasattr(record, "billable_event")
    ]


def client_context(name):
    parameters = (
        SimpleNamespace(clientInfo=SimpleNamespace(name=name))
        if name is not None
        else None
    )
    return SimpleNamespace(session=SimpleNamespace(client_params=parameters))


def test_every_registered_mcp_server_has_trigger_observation():
    from services.api.app import MCP_SERVERS

    assert len(MCP_SERVERS) == 10
    assert all(isinstance(server, ObservedMCP) for server in MCP_SERVERS)


@pytest.mark.asyncio
@pytest.mark.parametrize("client_name", ["actual-test-client", None])
async def test_mcp_cause_reaches_billable_boundary_without_tool_arguments(
    monkeypatch, caplog, client_name
):
    server = ObservedMCP("memory - test")
    monkeypatch.setattr(server, "get_context", lambda: client_context(client_name))

    @server.tool()
    async def observe(value: str) -> dict:
        with billable_operation("scripted", "request"):
            return {"observed": True}

    with trigger_context(request_id="request-123", origin="http", reason="parent"):
        before = current_trigger()
        await server.call_tool("observe", {"value": "PRIVATE_TOOL_ARGUMENT"})
        assert current_trigger() == before

    records = billable_records(caplog)
    assert [record["phase"] for record in records] == ["START", "END"]
    for record in records:
        assert {
            key: record[key]
            for key in (
                "trigger",
                "source",
                "tool",
                "client",
                "request_id",
                "origin",
                "reason",
            )
        } == {
            "trigger": "mcp",
            "source": "memory",
            "tool": "observe",
            "client": client_name or "unknown",
            "request_id": "request-123",
            "origin": "http",
            "reason": "mcp_tool",
        }
        assert "PRIVATE_TOOL_ARGUMENT" not in str(record)
    assert records[0]["event_id"] == records[1]["event_id"]
    assert current_trigger() == {}


@pytest.mark.asyncio
async def test_mcp_without_session_has_unknown_client_and_fresh_request_id(caplog):
    server = ObservedMCP("memory - test")

    @server.tool()
    async def observe() -> bool:
        with billable_operation("scripted", "request"):
            return True

    await server.call_tool("observe", {})

    records = billable_records(caplog)
    assert records[0]["client"] == "unknown"
    UUID(records[0]["request_id"])
    assert current_trigger() == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_mcp_failure_and_cancellation_restore_parent_context(failure):
    server = ObservedMCP("memory - test")

    @server.tool()
    async def fail() -> None:
        assert current_trigger()["tool"] == "fail"
        raise failure("synthetic failure")

    with trigger_context(trigger="http", request_id="parent-request"):
        before = current_trigger()
        with pytest.raises(
            ToolError if failure is RuntimeError else asyncio.CancelledError
        ):
            await server.call_tool("fail", {})
        assert current_trigger() == before


@pytest.mark.asyncio
async def test_concurrent_mcp_clients_keep_distinct_cause_contexts(monkeypatch, caplog):
    server = ObservedMCP("memory - test")
    context = ContextVar("test_mcp_client")
    monkeypatch.setattr(server, "get_context", context.get)
    both_entered = asyncio.Event()
    entered = 0

    @server.tool()
    async def observe() -> bool:
        nonlocal entered
        entered += 1
        if entered == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=2)
        with billable_operation("scripted", "request"):
            return True

    async def invoke(name):
        token = context.set(client_context(name))
        try:
            with trigger_context(request_id=name):
                await server.call_tool("observe", {})
        finally:
            context.reset(token)

    await asyncio.gather(invoke("first-client"), invoke("second-client"))

    records = billable_records(caplog)
    assert len(records) == 4
    assert {(record["request_id"], record["client"]) for record in records} == {
        ("first-client", "first-client"),
        ("second-client", "second-client"),
    }
    assert current_trigger() == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cause", [{}, {"trigger": "mcp", "reason": "mcp_tool", "request_id": "request-123"}]
)
async def test_graph_build_and_invocation_share_run_id_and_preserve_cause(
    monkeypatch, caplog, cause
):
    observed = []

    class Graph:
        async def ainvoke(self, inputs):
            observed.append(current_trigger())
            with billable_operation("scripted", "request"):
                return {"result": "ok"}

    def build():
        observed.append(current_trigger())
        return Graph()

    monkeypatch.setattr(
        runtime,
        "scan_library",
        lambda: {
            "probe": SimpleNamespace(
                INPUT_SCHEMA={"text": "string"}, build_graph=build
            ),
        },
    )
    with trigger_context(**cause):
        before = current_trigger()
        assert await runtime.dispatch("probe", {"text": "PRIVATE_GRAPH_INPUT"}) == "ok"
        assert current_trigger() == before

    assert observed[0] == observed[1]
    UUID(observed[0]["graph_run_id"])
    assert observed[0]["graph"] == "probe"
    assert observed[0]["trigger"] == cause.get("trigger", "graph")
    assert observed[0]["reason"] == cause.get("reason", "unknown")
    assert all(
        "PRIVATE_GRAPH_INPUT" not in str(record) for record in billable_records(caplog)
    )
    assert current_trigger() == {}


@pytest.mark.asyncio
async def test_graph_failure_restores_parent_context(monkeypatch):
    class Graph:
        async def ainvoke(self, inputs):
            raise RuntimeError("synthetic failure")

    monkeypatch.setattr(
        runtime,
        "scan_library",
        lambda: {
            "probe": SimpleNamespace(INPUT_SCHEMA={}, build_graph=Graph),
        },
    )
    with trigger_context(trigger="job", graph_run_id="outer-run"):
        before = current_trigger()
        with pytest.raises(RuntimeError, match="synthetic failure"):
            await runtime.dispatch("probe", {})
        assert current_trigger() == before
