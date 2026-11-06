import asyncio
from contextvars import ContextVar
from copy import deepcopy
import json
import logging
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import LATEST_PROTOCOL_VERSION
import pytest

from services import observability
from services.action_items import db as action_db
from services.action_items.server import create_server
from services.graphs import agents
from services.mcp_observability import ObservedMCP
from tests.test_mcp_transport import MCP_HEADERS, _json_rpc_payload
from tests.test_meeting_memory_agent import ScriptedModel, call


@pytest.fixture(autouse=True)
def capture_owned_logging(caplog):
    caplog.set_level(logging.DEBUG, logger="agent_smith.action")
    caplog.set_level(logging.DEBUG, logger="agent_smith.billable")


def client_context(name):
    return SimpleNamespace(
        session=SimpleNamespace(
            client_params=SimpleNamespace(clientInfo=SimpleNamespace(name=name))
        )
    )


def invocation_entries(caplog):
    return [
        record
        for record in caplog.records
        if record.levelno == logging.INFO and hasattr(record, "operation_event")
    ]


def assert_invocation(record, agent, tool, arguments, *, mcp=True):
    prefix = f"MCP {tool} " if mcp else f"{agent} {tool} "
    assert record.getMessage().startswith(prefix)
    assert json.loads(record.getMessage()[len(prefix) :]) == arguments
    assert record.operation_event["agent"] == agent
    assert record.operation_event["tool"] == tool
    assert record.operation_event["params"] == arguments
    assert record.operation_event["phase"] == "START"
    assert record.operation_event["event_id"]


def terminal_entries(caplog):
    return [
        record.operation_event
        for record in caplog.records
        if getattr(record, "operation_event", {}).get("phase") == "END"
    ]


def assert_params_are_entry_only(caplog):
    for record in caplog.records:
        provider = getattr(record, "billable_event", None)
        if provider is not None:
            assert "params" not in provider
        terminal = getattr(record, "operation_event", None)
        if terminal is not None and terminal.get("phase") == "END":
            assert "params" not in terminal


@pytest.mark.asyncio
async def test_mcp_complete_query_and_filters_are_logged_before_handler(
    monkeypatch, caplog
):
    server = ObservedMCP("memory - logging test")
    monkeypatch.setattr(
        server,
        "get_context",
        lambda: client_context("codex"),
    )
    arguments = {
        "query": "release ownership décisions 東京 " * 80 + "COMPLETE_QUERY_SUFFIX",
        "tags": ["architecture", "café"],
        "filters": {"nested": {"any": [False, 0, None, ""]}},
    }

    @server.tool()
    async def memory_search(query: str, tags: list[str], filters: dict) -> dict:
        entries = invocation_entries(caplog)
        assert len(entries) == 1
        assert_invocation(entries[0], "codex", "memory_search", arguments)
        assert {"query": query, "tags": tags, "filters": filters} == arguments
        return {"result": "RESULT_ONLY_DO_NOT_LOG"}

    await server.call_tool("memory_search", arguments)
    assert len(invocation_entries(caplog)) == 1
    assert "RESULT_ONLY_DO_NOT_LOG" not in caplog.text
    assert_params_are_entry_only(caplog)


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [None, {}])
async def test_omitted_arguments_remain_empty_with_unknown_caller(caplog, arguments):
    server = ObservedMCP("memory - logging test")

    @server.tool()
    def memory_list() -> list:
        assert_invocation(invocation_entries(caplog)[0], "unknown", "memory_list", {})
        return []

    if arguments is None:
        await server.call_tool("memory_list")
    else:
        await server.call_tool("memory_list", arguments)
    assert len(invocation_entries(caplog)) == 1
    assert_params_are_entry_only(caplog)


@pytest.mark.asyncio
async def test_exact_names_and_json_controls_cannot_forge_multiline_logs(
    monkeypatch, caplog
):
    server = ObservedMCP("memory - logging test")
    monkeypatch.setattr(server, "get_context", lambda: client_context("codex\nFORGED"))
    arguments = {"query": 'line one\nline two\r\t"quoted" 東京'}

    @server.tool(name="memory_search")
    def search(query: str) -> str:
        return "safe result"

    await server.call_tool("memory_search", arguments)
    record = invocation_entries(caplog)[0]
    prefix = "MCP memory_search "
    assert record.getMessage().startswith(prefix)
    assert json.loads(record.getMessage()[len(prefix) :]) == arguments
    assert "\n" not in record.getMessage()
    assert record.operation_event["agent"] == "codex\nFORGED"
    assert record.operation_event["tool"] == "memory_search"


@pytest.mark.asyncio
async def test_large_supported_content_is_complete_in_display_and_structured_entry(
    monkeypatch, caplog
):
    server = ObservedMCP("memory - logging test")
    monkeypatch.setattr(server, "get_context", lambda: client_context("codex"))
    arguments = {"content": "café 東京 " * 15000 + "FINAL_LARGE_CONTENT_SUFFIX"}
    assert len(arguments["content"]) > 100000

    @server.tool()
    def memory_add(content: str) -> str:
        assert content == arguments["content"]
        assert_invocation(
            invocation_entries(caplog)[0], "codex", "memory_add", arguments
        )
        return "large-fixture-id"

    await server.call_tool("memory_add", arguments)
    assert len(invocation_entries(caplog)) == 1


@pytest.mark.asyncio
async def test_non_json_direct_argument_logs_safe_marker_without_repr_or_mutation(
    monkeypatch, caplog
):
    class UnsupportedArgument:
        def __repr__(self):
            raise AssertionError("Argument logging must not inspect arbitrary repr")

    server = ObservedMCP("memory - logging test")
    monkeypatch.setattr(server, "get_context", lambda: client_context("codex"))
    value = UnsupportedArgument()

    @server.tool()
    def memory_search(query: Any) -> str:
        assert query is value
        return "supported-direct-result"

    await server.call_tool("memory_search", {"query": value})
    assert_invocation(
        invocation_entries(caplog)[0],
        "codex",
        "memory_search",
        {"query": "[UNSERIALIZABLE]"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [{"limit": 0}, {"limit": "1"}, {"unknown": True}])
async def test_invalid_contract_arguments_log_once_before_database_rejection(
    monkeypatch, caplog, arguments
):
    database_calls = []
    monkeypatch.setattr(
        action_db, "list_items", lambda values: database_calls.append(values)
    )
    server = create_server()
    monkeypatch.setattr(server, "get_context", lambda: client_context("codex"))

    with pytest.raises(ToolError):
        await server.call_tool("action_item_list", arguments)

    assert database_calls == []
    entries = invocation_entries(caplog)
    assert len(entries) == 1
    assert_invocation(entries[0], "codex", "action_item_list", arguments)
    terminal = terminal_entries(caplog)
    assert len(terminal) == 1 and terminal[0]["outcome"] == "failed"
    assert terminal[0]["event_id"] == entries[0].operation_event["event_id"]
    assert_params_are_entry_only(caplog)


@pytest.mark.asyncio
async def test_unknown_contract_tool_retains_submitted_name_and_arguments(
    monkeypatch, caplog
):
    server = create_server()
    monkeypatch.setattr(server, "get_context", lambda: client_context("codex"))
    arguments = {"query": "unrecognized operation", "tags": []}

    with pytest.raises(ToolError, match="No input contract"):
        await server.call_tool("future_tool_exact_name", arguments)

    entries = invocation_entries(caplog)
    assert len(entries) == 1
    assert_invocation(entries[0], "codex", "future_tool_exact_name", arguments)
    assert entries[0].operation_event["billing"] == "unknown"


@pytest.mark.asyncio
async def test_concurrent_calls_keep_immutable_arguments_and_caller_context(
    monkeypatch, caplog
):
    server = ObservedMCP("memory - logging test")
    caller = ContextVar("argument_logging_caller")
    monkeypatch.setattr(server, "get_context", lambda: client_context(caller.get()))
    entered = asyncio.Barrier(3)
    release = asyncio.Event()
    arguments = [
        {"query": name + " original", "filters": {"tags": [name], "value": None}}
        for name in ("codex", "claude")
    ]
    expected = deepcopy(arguments)

    @server.tool()
    async def memory_search(query: str, filters: dict) -> str:
        await entered.wait()
        await release.wait()
        return "CONCURRENT_RESULT_ONLY"

    async def invoke(name, values):
        token = caller.set(name)
        try:
            with observability.trigger_context(request_id=f"request-{name}"):
                before = observability.current_trigger()
                await server.call_tool("memory_search", values)
                assert observability.current_trigger() == before
        finally:
            caller.reset(token)

    tasks = [
        asyncio.create_task(invoke(name, values))
        for name, values in zip(("codex", "claude"), arguments, strict=True)
    ]
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        for values in arguments:
            values["query"] = "LATE_CALLER_MUTATION"
            values["filters"]["tags"].append("late")
        release.set()
        await asyncio.gather(*tasks)
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    entries = invocation_entries(caplog)
    assert len(entries) == 2
    for name, values in zip(("codex", "claude"), expected, strict=True):
        entry = next(
            record for record in entries if record.operation_event["client"] == name
        )
        assert_invocation(entry, name, "memory_search", values)
        assert entry.operation_event["request_id"] == f"request-{name}"
    assert len({record.operation_event["event_id"] for record in entries}) == 2
    assert observability.current_trigger() == {}
    assert "LATE_CALLER_MUTATION" not in caplog.text
    assert "CONCURRENT_RESULT_ONLY" not in caplog.text
    assert_params_are_entry_only(caplog)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_failure_and_cancellation_preserve_correlation_and_restore_context(
    monkeypatch, caplog, cancel
):
    server = ObservedMCP("memory - logging test")
    monkeypatch.setattr(server, "get_context", lambda: client_context("codex"))
    cancellation = asyncio.CancelledError("CANCEL_DETAIL_NOT_A_PARAMETER")
    arguments = {"query": "failure-path query", "tags": ["diagnostics"]}

    @server.tool()
    async def memory_search(query: str, tags: list[str]) -> str:
        assert_invocation(
            invocation_entries(caplog)[0], "codex", "memory_search", arguments
        )
        if cancel:
            raise cancellation
        raise RuntimeError("ERROR_DETAIL_NOT_A_PARAMETER")

    with observability.trigger_context(request_id="outer-request", origin="test"):
        before = observability.current_trigger()
        with pytest.raises(asyncio.CancelledError if cancel else ToolError) as caught:
            await server.call_tool("memory_search", arguments)
        if cancel:
            assert caught.value is cancellation
        assert observability.current_trigger() == before

    entries = invocation_entries(caplog)
    assert len(entries) == 1
    terminal = terminal_entries(caplog)
    assert len(terminal) == 1
    assert terminal[0]["outcome"] == ("cancelled" if cancel else "failed")
    assert terminal[0]["event_id"] == entries[0].operation_event["event_id"]
    assert terminal[0]["request_id"] == "outer-request"
    assert observability.current_trigger() == {}
    assert_params_are_entry_only(caplog)


@pytest.mark.asyncio
async def test_redaction_preserves_search_semantics_and_original_arguments(
    monkeypatch, caplog
):
    server = ObservedMCP("memory - logging test")
    monkeypatch.setattr(server, "get_context", lambda: client_context("codex"))
    arguments = {
        "query": "opaqueIdentifier" * 80,
        "tags": ["security", "東京"],
        "filters": {
            "headers": {
                "Authorization": "Bearer PRIVATE_HEADER_CREDENTIAL",
                "Accept": "application/json",
            },
            "env": {"AWS_SECRET_ACCESS_KEY": "PRIVATE_ENV_CREDENTIAL"},
            "nested": [{"api_key": "PRIVATE_NESTED_CREDENTIAL", "active": False}],
            "text": "Look for Bearer PRIVATE_INLINE_CREDENTIAL near release notes",
            "private_key": "-----BEGIN PRIVATE KEY-----\nPRIVATE_KEY_BODY\n-----END PRIVATE KEY-----",
            "max_tokens": 256,
            "token_count": 0,
            "missing": None,
            "empty": "",
        },
    }
    original = deepcopy(arguments)

    @server.tool()
    def memory_search(query: str, tags: list[str], filters: dict) -> str:
        assert {"query": query, "tags": tags, "filters": filters} == original
        return "REDACTION_RESULT_ONLY"

    await server.call_tool("memory_search", arguments)
    assert arguments == original
    entry = invocation_entries(caplog)[0]
    displayed = json.loads(entry.getMessage().removeprefix("MCP memory_search "))
    assert entry.operation_event["params"] == displayed
    assert displayed["query"] == original["query"]
    assert displayed["tags"] == original["tags"]
    for key in ("max_tokens", "token_count", "missing", "empty"):
        assert displayed["filters"][key] == original["filters"][key]
    assert displayed["filters"]["headers"]["Accept"] == "application/json"
    assert displayed["filters"]["nested"][0]["active"] is False
    for value in (
        "PRIVATE_HEADER_CREDENTIAL",
        "PRIVATE_ENV_CREDENTIAL",
        "PRIVATE_NESTED_CREDENTIAL",
        "PRIVATE_INLINE_CREDENTIAL",
        "PRIVATE_KEY_BODY",
        "REDACTION_RESULT_ONLY",
    ):
        assert value not in caplog.text
    assert_params_are_entry_only(caplog)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_native_agent_logs_role_and_submitted_arguments_without_provider_leak(
    monkeypatch, caplog, mode
):
    arguments = {
        "query": "complete native agent café query " * 60,
        "tags": ["architecture", "testing"],
    }

    @tool("search_memories")
    def search(query: str, tags: list[str]) -> str:
        """Read prior memories for a scripted offline agent."""
        assert_invocation(
            invocation_entries(caplog)[0],
            "curator",
            "search_memories",
            arguments,
            mcp=False,
        )
        assert {"query": query, "tags": tags} == arguments
        with observability.billable_operation("pinecone", "query"):
            return "NATIVE_RESULT_ONLY"

    model = ScriptedModel(
        replies=[call("search_memories", **arguments), AIMessage(content="finished")]
    )
    monkeypatch.setattr(agents, "build_chat_model", lambda *args, **kwargs: model)
    agent = agents.create_tool_agent(
        system_prompt="offline test", model_role="curator", tools=[search]
    )
    inputs = {"messages": [HumanMessage(content="test")]}
    result = await agent.ainvoke(inputs) if mode == "async" else agent.invoke(inputs)
    assert result["messages"][-1].content == "finished"
    assert result["messages"][-2].content == "NATIVE_RESULT_ONLY"
    assert len(invocation_entries(caplog)) == 1
    assert "NATIVE_RESULT_ONLY" not in caplog.text
    providers = [
        record.billable_event
        for record in caplog.records
        if hasattr(record, "billable_event")
    ]
    assert len(providers) == 2
    assert providers[0]["event_id"] == providers[1]["event_id"]
    assert providers[0]["agent_tool"] == "search_memories"
    assert all(arguments["query"] not in str(record) for record in providers)
    assert observability.current_trigger() == {}
    assert_params_are_entry_only(caplog)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_tags", [False, True])
async def test_http_memory_tools_call_logs_exact_submission_without_live_search(
    monkeypatch, caplog, with_tags
):
    from services.api.mcp_transport import MCPSSECompletionMiddleware
    from services.memory import db
    from services.memory import server as memory_server

    server = ObservedMCP("memory - isolated transport test")
    server.add_tool(memory_server.memory_search)
    server.settings.streamable_http_path = "/"
    server.settings.stateless_http = True
    transport_app = server.streamable_http_app()
    transport_app.add_middleware(MCPSSECompletionMiddleware)
    app = FastAPI()
    app.mount("/mcp/memory", transport_app)

    arguments = {
        "query": "HTTP semantic query café 東京 " * 80 + "HTTP_COMPLETE_SUFFIX",
        "repo": "agent-smith",
        "limit": 7,
    }
    if with_tags:
        arguments.update(tags=["architecture", "memory"], meeting_only=True)
    searched = []

    def search(**submitted):
        entries = invocation_entries(caplog)
        assert len(entries) == 1
        assert_invocation(entries[0], "unknown", "memory_search", arguments)
        searched.append(submitted)
        return [{"id": "fake-memory", "content": "HTTP_RESULT_ONLY"}]

    monkeypatch.setattr(db, "search", search)
    async with server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:7654"
        ) as client:
            initialized = await client.post(
                "/mcp/memory/",
                headers=MCP_HEADERS,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": LATEST_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "http-codex", "version": "test"},
                    },
                },
            )
            assert initialized.status_code == 200
            assert "result" in _json_rpc_payload(initialized)
            response = await client.post(
                "/mcp/memory/",
                headers=MCP_HEADERS,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "memory_search", "arguments": arguments},
                },
            )

    assert response.status_code == 200
    payload = _json_rpc_payload(response)["result"]
    assert payload.get("isError") is not True
    assert "HTTP_RESULT_ONLY" in str(payload)
    assert searched == [
        {
            **arguments,
            "tags": arguments.get("tags"),
            "meeting_only": arguments.get("meeting_only", False),
        }
    ]
    assert len(invocation_entries(caplog)) == 1
    assert "HTTP_RESULT_ONLY" not in caplog.text
    assert_params_are_entry_only(caplog)
