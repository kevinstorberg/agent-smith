from __future__ import annotations

import importlib

import pytest

from services.config import ALL_AGENTS, DASHBOARD_PORT, MCP_URL
import services.config


def test_all_agents_is_nonempty_list():
    assert isinstance(ALL_AGENTS, list)
    assert len(ALL_AGENTS) > 0


def test_all_agents_contains_known_agents():
    assert "claude" in ALL_AGENTS
    assert "codex" in ALL_AGENTS
    assert "gemini" in ALL_AGENTS


def test_all_agents_are_strings():
    for agent in ALL_AGENTS:
        assert isinstance(agent, str)


def test_dashboard_port_is_digit_string():
    assert DASHBOARD_PORT.isdigit()


def test_mcp_url_format():
    assert MCP_URL.startswith("http://localhost:")
    assert MCP_URL.endswith("/mcp/")
    assert DASHBOARD_PORT in MCP_URL


def test_crashes_if_not_test_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    with pytest.raises(SystemExit, match="Tests can only run in APP_ENV=test"):
        importlib.reload(services.config)
    monkeypatch.setenv("APP_ENV", "test")
    importlib.reload(services.config)
