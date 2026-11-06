from dataclasses import FrozenInstanceError
import json

import pytest

from scripts.shared.claude_memory_redaction import redact_for_capture


def capture(arguments, *, agent="codex", tool="memory_search"):
    from scripts.shared.tool_logging import ToolInvocation

    return ToolInvocation.capture(agent=agent, tool=tool, arguments=arguments)


def test_complete_parameters_are_an_immutable_json_snapshot():
    query = "Architecture decisions and ownership café " * 400 + " final identifier"
    arguments = {
        "query": query,
        "repo": "agent-smith",
        "tags": ["architecture", "decision"],
        "filters": {"nested": [{"enabled": False, "count": 0, "missing": None}]},
        "limit": 25,
        "meeting_only": False,
        "empty": "",
    }
    expected = json.loads(json.dumps(arguments))
    invocation = capture(arguments)
    arguments["query"] = "mutated"
    arguments["tags"].append("later")
    arguments["filters"]["nested"][0]["enabled"] = True
    assert json.loads(invocation.params_json) == expected
    assert invocation.prefix == "codex memory_search"
    with pytest.raises(FrozenInstanceError):
        invocation.params_json = "changed"


def test_credentials_are_redacted_without_mutating_the_invocation():
    arguments = {
        "query": "release ownership",
        "tags": ["security"],
        "headers": {"Authorization": "Bearer confidential", "X-API-Key": "hidden"},
        "nested": [{"client_secret": "private", "password": "private"}],
        "api_key": "private",
        "max_tokens": 256,
        "inline": "password=inline-private-value",
    }
    invocation = capture(arguments)
    logged = json.loads(invocation.params_json)
    assert logged["query"] == arguments["query"]
    assert logged["tags"] == ["security"]
    assert logged["max_tokens"] == 256
    assert logged["headers"] == {
        "Authorization": "[REDACTED]",
        "X-API-Key": "[REDACTED]",
    }
    assert logged["nested"] == [
        {"client_secret": "[REDACTED]", "password": "[REDACTED]"}
    ]
    assert "private" not in invocation.params_json
    assert "confidential" not in invocation.params_json
    assert "hidden" not in invocation.params_json
    assert arguments["api_key"] == "private"
    assert arguments["headers"]["Authorization"] == "Bearer confidential"


def test_vendor_tokens_and_credentials_in_field_names_are_redacted():
    arguments = {
        "content": {
            "env": {"GITHUB_TOKEN": "github-private", "HF_TOKEN": "hf-private"}
        },
        "password=inline-key-private": "ordinary value",
        "max_tokens": 256,
        "token_count": 12,
    }
    invocation = capture(arguments)
    logged = json.loads(invocation.params_json)
    assert logged["content"]["env"] == {
        "GITHUB_TOKEN": "[REDACTED]",
        "HF_TOKEN": "[REDACTED]",
    }
    assert "private" not in invocation.params_json
    assert "ordinary value" in logged.values()
    assert logged["max_tokens"] == 256 and logged["token_count"] == 12
    assert arguments["content"]["env"]["GITHUB_TOKEN"] == "github-private"


def test_logging_preserves_opaque_identifiers_without_changing_capture_policy():
    identifier = "opaqueIdentifier" * 150 + "CompleteSuffix"
    assert redact_for_capture(identifier) == "*" * len(identifier)
    assert json.loads(capture({"query": identifier}).params_json) == {
        "query": identifier
    }
    private_key = (
        "-----BEGIN PRIVATE KEY-----\nprivate material\n-----END PRIVATE KEY-----"
    )
    assert "private material" not in capture({"content": private_key}).params_json


def test_unavailable_identity_and_absent_arguments_are_honest():
    invocation = capture(None, agent="")
    assert invocation.prefix == "unknown memory_search"
    assert json.loads(invocation.params_json) == {}
    assert json.loads(capture({"query": None, "tags": []}).params_json) == {
        "query": None,
        "tags": [],
    }


def test_large_tool_content_reaches_the_emitted_snapshot_without_a_size_cap():
    content = ("complete source content " * 5_000) + " FINAL_CONTENT_IDENTIFIER"
    assert len(content) > 100_000
    assert json.loads(capture({"content": content}).params_json)["content"] == content


def test_control_characters_cannot_forge_log_lines():
    invocation = capture(
        {"query": 'first\nsecond\r\t"quoted"'},
        agent="codex\nFORGED",
        tool="search\rFORGED",
    )
    assert "\n" not in invocation.prefix
    assert "\r" not in invocation.prefix
    assert "\n" not in invocation.params_json
    assert json.loads(invocation.params_json)["query"] == 'first\nsecond\r\t"quoted"'


def test_credentials_in_untrusted_identity_strings_are_masked_before_storage():
    invocation = capture(
        {}, agent="Bearer client-private", tool="password=tool-private"
    )
    assert "private" not in invocation.agent
    assert "private" not in invocation.tool
    assert "private" not in invocation.prefix


@pytest.mark.asyncio
async def test_client_identity_credentials_do_not_reach_provider_or_terminal_logs(
    monkeypatch, caplog
):
    import logging
    from services.mcp_observability import ObservedMCP
    from services.observability import billable_operation
    from tests.test_mcp_observability import client_context

    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="agent_smith.action")
    caplog.set_level(logging.DEBUG, logger="agent_smith.billable")
    monkeypatch.setenv("MEMORY_BACKEND", "lancedb")
    server = ObservedMCP("memory - test")
    monkeypatch.setattr(
        server, "get_context", lambda: client_context("Bearer client-private")
    )

    @server.tool()
    def memory_search(query: str) -> str:
        with billable_operation("synthetic", "read"):
            return "result"

    await server.call_tool("memory_search", {"query": "public decisions"})
    assert "client-private" not in caplog.text
    observed = [
        getattr(record, "operation_event", getattr(record, "billable_event", {}))
        for record in caplog.records
    ]
    assert all("client-private" not in str(record) for record in observed)


def test_non_json_direct_calls_do_not_invoke_arbitrary_repr():
    class Unprintable:
        def __repr__(self):
            raise AssertionError("Parameter logging must never call repr")

    arguments = {"value": Unprintable()}
    invocation = capture(arguments)
    assert json.loads(invocation.params_json)["value"] == "[UNSERIALIZABLE]"
    assert isinstance(arguments["value"], Unprintable)


def test_non_json_cycles_and_nonfinite_values_cannot_break_tool_execution():
    arguments = {"query": "complete query", "nan": float("nan")}
    arguments["cycle"] = arguments
    logged = json.loads(capture(arguments).params_json)
    assert logged == {
        "query": "complete query",
        "nan": "[NONFINITE]",
        "cycle": "[CIRCULAR]",
    }
