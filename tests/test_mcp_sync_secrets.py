"""Sync withholds MCP servers whose ${VAR} config is unset or still the .env.default placeholder.

A placeholder token deploys as a guaranteed 401, and Claude Code disables its OAuth
fallback whenever an Authorization header is configured, so it must fail at sync time.
"""
from __future__ import annotations

import json

import pytest

from scripts.shared import mcp_utils
from scripts.shared.agents import AGENT_TARGETS
from services.api.models import tool as tool_model

SLACK = {"url": "https://mcp.slack.com/mcp", "headers": {"Authorization": "Bearer ${SLACK_ACCESS_TOKEN}"}}
LOCAL = {"url": "http://localhost:${DASHBOARD_PORT}/mcp/memory/"}
DEFAULTS = {"SLACK_ACCESS_TOKEN": "slack-access-token", "DASHBOARD_PORT": "7654"}


def test_unset_reference_is_unusable():
    assert mcp_utils.unusable_env_references(SLACK, environ={}, defaults=DEFAULTS) == ["SLACK_ACCESS_TOKEN"]


def test_secret_left_at_its_placeholder_is_unusable():
    environ = {"SLACK_ACCESS_TOKEN": "slack-access-token"}
    assert mcp_utils.unusable_env_references(SLACK, environ, DEFAULTS) == ["SLACK_ACCESS_TOKEN"]


def test_real_secret_and_non_secret_default_are_usable():
    environ = {"SLACK_ACCESS_TOKEN": "xoxp-real", "DASHBOARD_PORT": "7654"}
    assert mcp_utils.unusable_env_references(SLACK, environ, DEFAULTS) == []
    assert mcp_utils.unusable_env_references(LOCAL, environ, DEFAULTS) == []


@pytest.fixture
def claude_config(tmp_path, monkeypatch):
    dest = tmp_path / "claude.json"
    monkeypatch.setitem(AGENT_TARGETS["claude"], "mcp_file", str(dest))
    (tmp_path / ".env.default").write_text("SLACK_ACCESS_TOKEN=slack-access-token\n", encoding="utf-8")
    monkeypatch.setattr(mcp_utils, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        tool_model,
        "collect_tools_from_db",
        lambda agent: {"Slack": SLACK, "memory": {"url": "http://localhost:7654/mcp/memory/"}},
    )
    return dest


def _deployed(dest) -> dict:
    return json.loads(dest.read_text(encoding="utf-8"))["mcpServers"]


def test_sync_withholds_placeholder_server_and_deploys_the_rest(claude_config, monkeypatch, capsys):
    monkeypatch.setenv("SLACK_ACCESS_TOKEN", "slack-access-token")

    errors = mcp_utils.sync_mcp("claude", dry_run=False)

    assert list(_deployed(claude_config)) == ["memory"]
    assert len(errors) == 1 and "Slack" in errors[0] and "SLACK_ACCESS_TOKEN" in errors[0]
    assert "ERROR" in capsys.readouterr().out


def test_sync_deploys_server_once_its_secret_is_set(claude_config, monkeypatch):
    monkeypatch.setenv("SLACK_ACCESS_TOKEN", "xoxp-real")

    assert mcp_utils.sync_mcp("claude", dry_run=False) == []
    assert _deployed(claude_config)["Slack"]["headers"]["Authorization"] == "Bearer xoxp-real"


def test_single_item_sync_reports_a_withheld_server_as_failure(claude_config, monkeypatch):
    from scripts.shared.fs import sync_item
    from services.api.models.shared import harness

    monkeypatch.setenv("SLACK_ACCESS_TOKEN", "slack-access-token")
    monkeypatch.setattr(harness, "get_item_by_id", lambda item_type, item_id: {"name": "Slack", "agents": ["claude"]})

    result = sync_item("tool", 7)

    assert result["success"] is False
    assert "SLACK_ACCESS_TOKEN" in result["message"]
