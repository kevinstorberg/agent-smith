"""Stdio MCP server support in sync.

A tool item's metadata is either stdio (a local ``command`` with optional
``args``/``env``) or http (a remote ``url``). The per-agent ``mcp_transform`` emits the
right server-config shape for each; existing http items must be unaffected.
"""
from __future__ import annotations

import pytest

from scripts.reverse_sync import _reverse_mcp_transform
from scripts.shared.agents import AGENT_TARGETS, _build_mcp_entry
from scripts.shared.env import expand_env

STDIO = {
    "command": "npx",
    "args": ["-y", "@softeria/ms-365-mcp-server", "--org-mode"],
    "env": {"MS365_MCP_TENANT_ID": "935a74f4"},
    "description": "Teams via Graph",
}


def _transform(agent, srv):
    return AGENT_TARGETS[agent]["mcp_transform"](srv)


# --- forward: stdio per agent -------------------------------------------------

def test_claude_stdio_includes_type():
    assert _transform("claude", STDIO) == {
        "type": "stdio",
        "command": "npx",
        "args": STDIO["args"],
        "env": STDIO["env"],
    }


def test_codex_stdio_omits_type():
    entry = _transform("codex", STDIO)
    assert entry == {"command": "npx", "args": STDIO["args"], "env": STDIO["env"]}
    assert "type" not in entry


def test_gemini_stdio_omits_type():
    entry = _transform("gemini", STDIO)
    assert entry == {"command": "npx", "args": STDIO["args"], "env": STDIO["env"]}
    assert "type" not in entry


def test_stdio_omits_empty_args_and_env():
    assert _transform("claude", {"command": "foo"}) == {"type": "stdio", "command": "foo"}


# --- forward: http regression (unchanged behavior) ----------------------------

def test_claude_http_unchanged():
    srv = {"url": "https://x/mcp", "headers": {"Authorization": "Bearer t"}, "oauth": {"clientId": "c"}}
    assert _transform("claude", srv) == {
        "type": "http",
        "url": "https://x/mcp",
        "headers": {"Authorization": "Bearer t"},
        "oauth": {"clientId": "c"},
    }


def test_codex_http_unchanged():
    assert _transform("codex", {"url": "https://x/mcp"}) == {"url": "https://x/mcp"}


def test_gemini_http_uses_httpurl():
    assert _transform("gemini", {"url": "https://x/mcp"}) == {"httpUrl": "https://x/mcp"}


# --- contract: crash early on neither -----------------------------------------

def test_build_entry_crashes_on_neither_command_nor_url():
    with pytest.raises(ValueError, match="'command' .*or 'url'"):
        _build_mcp_entry({"description": "x"}, url_key="url", emit_type=True, http_extra=())


# --- env expansion through the real sync path ---------------------------------

def test_env_var_expands_inside_stdio_env(monkeypatch):
    monkeypatch.setenv("TOK", "secret")
    out = expand_env({"command": "npx", "env": {"K": "${TOK}"}})
    assert out["env"]["K"] == "secret"


# --- reverse: symmetry --------------------------------------------------------

def test_reverse_stdio_round_trip():
    cfg = {"type": "stdio", "command": "npx", "args": ["-y", "x"], "env": {"A": "1"}}
    assert _reverse_mcp_transform("claude", cfg) == {
        "command": "npx",
        "args": ["-y", "x"],
        "env": {"A": "1"},
    }


def test_reverse_http_still_maps_url():
    assert _reverse_mcp_transform("gemini", {"httpUrl": "https://x/mcp"}) == {"url": "https://x/mcp"}
