#!/usr/bin/env -S .venv/bin/python3
"""PreToolUse / PostToolUse audit hook for coding agents.

Reads the agent's hook JSON on stdin, normalizes it across Claude/Codex/Gemini,
and POSTs one event to the dashboard's ingest API. It runs on the host (the
dashboard + DB run in Docker), so it talks HTTP, not SQL, and uses only the
standard library to stay fast and dependency-free.

CONTRACT: this hook is pure observation. It ALWAYS exits 0 and writes nothing to
stdout, so a missing dashboard, a slow network, or a malformed payload can never
block or alter the agent's tool call (fail-open).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request

# Kept in lockstep with services.api.routers.audit._cap / MAX_FIELD_CHARS
# (intentional cross-boundary copy — this host script must not import services.*);
# behavioral parity is pinned by tests/test_audit_consistency.py.
MAX_FIELD_CHARS = 8192
POST_TIMEOUT_SECONDS = 2

# Per-agent candidate keys for each logical field, tried in order. Claude is
# documented; Codex/Gemini lists are best-effort and refined from live payloads.
# The keys are also the hook's agent list, kept in lockstep with
# services.api.models.audit.AUDIT_AGENTS (pinned by tests/test_audit_consistency.py).
FIELD_KEYS = {
    "claude": {
        "tool_name": ("tool_name",),
        "tool_input": ("tool_input",),
        "session_id": ("session_id",),
        "cwd": ("cwd",),
        "native_id": ("tool_use_id", "tool_call_id"),
        "result": ("tool_response",),
        "event_name": ("hook_event_name",),
    },
    "codex": {
        "tool_name": ("tool_name", "tool", "name"),
        "tool_input": ("tool_input", "arguments", "input"),
        "session_id": ("session_id", "session", "conversation_id"),
        "cwd": ("cwd", "workdir", "working_directory"),
        "native_id": ("tool_call_id", "call_id", "id"),
        "result": ("tool_response", "output", "result"),
        "event_name": ("hook_event_name", "event", "type"),
    },
    "gemini": {
        "tool_name": ("toolName", "tool_name", "name"),
        "tool_input": ("toolInput", "args", "input"),
        "session_id": ("sessionId", "session_id"),
        "cwd": ("cwd", "workingDirectory"),
        "native_id": ("toolCallId", "callId", "id"),
        "result": ("toolResponse", "response", "output"),
        "event_name": ("hookEventName", "event"),
    },
}


def detect_agent(payload: dict) -> str:
    """Infer which coding agent produced this payload.

    One hook item is assigned to several agents, and the sync writes the same
    command to each of their settings files, so the agent is not a CLI arg — we
    read it off the payload shape. Claude is reliable (documented keys); Codex and
    Gemini are best-effort until refined against a live payload.
    """
    keys = payload.keys()
    if any(k in keys for k in ("hookEventName", "toolName", "sessionId", "toolCallId")):
        return "gemini"
    if any(k in keys for k in ("hook_event_name", "tool_use_id", "tool_input")):
        return "claude"
    return "codex"


def _first(payload: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _cap(value):
    """Truncate oversized string leaves so the POST body stays bounded."""
    if isinstance(value, dict):
        return {k: _cap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap(v) for v in value]
    if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
        return value[:MAX_FIELD_CHARS] + f"...[truncated {len(value) - MAX_FIELD_CHARS} chars]"
    return value


def _correlation_key(native_id, session_id: str, tool_name: str, tool_input) -> str:
    if native_id:
        return str(native_id)
    canonical = json.dumps(
        [session_id, tool_name, tool_input], sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _derive_status(explicit: str | None, event_name) -> str:
    if explicit:
        return explicit
    if event_name and "fail" in str(event_name).lower():
        return "error"
    return "success"


def build_payload(agent: str, phase: str, status: str | None, payload: dict) -> dict:
    """Normalize one agent hook payload into the ingest API's event shape."""
    keys = FIELD_KEYS[agent]
    tool_input = _first(payload, keys["tool_input"])
    if not isinstance(tool_input, dict):
        tool_input = {"value": tool_input} if tool_input is not None else {}
    session_id = str(_first(payload, keys["session_id"]) or "unknown")
    tool_name = str(_first(payload, keys["tool_name"]) or "unknown")
    cwd = _first(payload, keys["cwd"])

    event = {
        "phase": phase,
        "agent": agent,
        "session_id": session_id,
        "tool_name": tool_name,
        "correlation_key": _correlation_key(
            _first(payload, keys["native_id"]), session_id, tool_name, tool_input
        ),
        "tool_input": _cap(tool_input),
        "cwd": cwd,
        "project": os.path.basename(cwd) if cwd else None,
    }
    if phase == "post":
        event["status"] = _derive_status(status, _first(payload, keys["event_name"]))
        result = _first(payload, keys["result"])
        if result is not None:
            event["result"] = _cap(result)
    return event


def _ingest_url() -> str:
    base = os.environ.get("AUDIT_INGEST_URL")
    if base:
        return base.rstrip("/")
    port = os.environ.get("DASHBOARD_PORT", "7654")
    return f"http://localhost:{port}/api/audit/events"


def _post(event: dict) -> None:
    data = json.dumps(event).encode("utf-8")
    req = urllib.request.Request(_ingest_url(), data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    token = os.environ.get("AUDIT_INGEST_TOKEN")
    if token:
        req.add_header("X-Audit-Token", token)
    urllib.request.urlopen(req, timeout=POST_TIMEOUT_SECONDS).close()


def run(argv: list[str], stdin_text: str) -> int:
    """Parse args + stdin, post the event, and ALWAYS return 0 (fail-open).

    The agent is auto-detected from the payload (one hook item serves all agents);
    only the phase (and optionally an explicit failure status) is passed as an arg.
    """
    try:
        parser = argparse.ArgumentParser(prog="scripts/audit_hook.py")
        parser.add_argument("--phase", required=True, choices=("pre", "post"))
        parser.add_argument("--status", choices=("success", "error"), default=None)
        args = parser.parse_args(argv)

        payload = json.loads(stdin_text) if stdin_text.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
        _post(build_payload(detect_agent(payload), args.phase, args.status, payload))
    except Exception as exc:  # never block the tool call
        if os.environ.get("AUDIT_DEBUG"):
            print(f"audit_hook: {exc}", file=sys.stderr)
    return 0


def main() -> int:
    return run(sys.argv[1:], sys.stdin.read())


if __name__ == "__main__":
    raise SystemExit(main())
