"""Unit tests for the host-side audit hook (tracer bullet 4). No network."""
from __future__ import annotations

import json

import scripts.audit_hook as hook

CLAUDE_PRE = {
    "hook_event_name": "PreToolUse",
    "session_id": "sess-1",
    "cwd": "/Users/kevin/projects/agent-smith",
    "tool_name": "Bash",
    "tool_input": {"command": "ls -la"},
    "tool_use_id": "toolu_abc",
}


def test_claude_pre_extraction_uses_native_id_and_derives_project():
    event = hook.build_payload("claude", "pre", None, CLAUDE_PRE)
    assert event == {
        "phase": "pre",
        "agent": "claude",
        "session_id": "sess-1",
        "tool_name": "Bash",
        "correlation_key": "toolu_abc",
        "tool_input": {"command": "ls -la"},
        "cwd": "/Users/kevin/projects/agent-smith",
        "project": "agent-smith",
    }


def test_claude_post_carries_result_and_success_status():
    payload = {**CLAUDE_PRE, "hook_event_name": "PostToolUse", "tool_response": {"stdout": "ok"}}
    event = hook.build_payload("claude", "post", None, payload)
    assert event["status"] == "success"
    assert event["result"] == {"stdout": "ok"}
    assert event["correlation_key"] == "toolu_abc"  # pairs with the pre event


def test_failure_event_name_derives_error_status():
    payload = {**CLAUDE_PRE, "hook_event_name": "PostToolUseFailure"}
    event = hook.build_payload("claude", "post", None, payload)
    assert event["status"] == "error"


def test_codex_alternate_keys():
    payload = {
        "tool": "shell",
        "arguments": {"cmd": "echo hi"},
        "conversation_id": "c-9",
        "workdir": "/tmp/proj",
        "call_id": "call_77",
    }
    event = hook.build_payload("codex", "pre", None, payload)
    assert event["tool_name"] == "shell"
    assert event["tool_input"] == {"cmd": "echo hi"}
    assert event["session_id"] == "c-9"
    assert event["correlation_key"] == "call_77"
    assert event["project"] == "proj"


def test_gemini_camelcase_keys():
    payload = {"toolName": "WriteFile", "args": {"path": "a"}, "sessionId": "g-1", "toolCallId": "tc1"}
    event = hook.build_payload("gemini", "pre", None, payload)
    assert event["tool_name"] == "WriteFile"
    assert event["correlation_key"] == "tc1"


def test_correlation_hash_fallback_is_stable_and_distinct():
    base = {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": "ls"}}
    a = hook.build_payload("claude", "pre", None, base)
    b = hook.build_payload("claude", "pre", None, dict(base))
    c = hook.build_payload("claude", "pre", None, {**base, "tool_input": {"command": "rm"}})
    assert a["correlation_key"] == b["correlation_key"]
    assert a["correlation_key"] != c["correlation_key"]
    assert len(a["correlation_key"]) == 16  # hash, not a native id


def test_oversized_fields_are_capped():
    payload = {**CLAUDE_PRE, "tool_input": {"command": "x" * 20000}}
    event = hook.build_payload("claude", "pre", None, payload)
    assert len(event["tool_input"]["command"]) < 9000
    assert event["tool_input"]["command"].endswith("chars]")


def test_detect_agent_from_payload_shape():
    assert hook.detect_agent(CLAUDE_PRE) == "claude"
    assert hook.detect_agent({"toolName": "WriteFile", "sessionId": "g"}) == "gemini"
    assert hook.detect_agent({"tool": "shell", "call_id": "x"}) == "codex"


def test_run_auto_detects_agent_and_posts(monkeypatch):
    captured = {}
    monkeypatch.setattr(hook, "_post", lambda event: captured.update(event))
    code = hook.run(["--phase", "pre"], json.dumps(CLAUDE_PRE))  # no --agent
    assert code == 0
    assert captured["agent"] == "claude"
    assert captured["correlation_key"] == "toolu_abc"


def test_run_is_fail_open_on_post_error(monkeypatch):
    def boom(event):
        raise OSError("dashboard down")

    monkeypatch.setattr(hook, "_post", boom)
    assert hook.run(["--phase", "post", "--status", "success"], json.dumps(CLAUDE_PRE)) == 0


def test_run_is_fail_open_on_garbage_stdin(monkeypatch):
    monkeypatch.setattr(hook, "_post", lambda event: None)
    assert hook.run(["--phase", "pre"], "not json {{{") == 0
