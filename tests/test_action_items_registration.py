from __future__ import annotations

import json
import tomllib

import pytest

from scripts.shared import mcp_utils
from scripts.shared.agents import AGENT_TARGETS
from services.api.models.shared.harness import get_item_by_id, update_content
from services.api.models.tool import collect_tools_from_db, get_tool
from services.config import MCP_BASE
from services.db import get_connection
from services.db import seed
from tests.conftest import clean_harness_rows


@pytest.fixture(autouse=True)
def isolated_action_items_tool(monkeypatch):
    clean_harness_rows("action-items")
    monkeypatch.setattr(seed, "MCP_SERVERS", [entry for entry in seed.MCP_SERVERS if entry[0] == "action-items"])
    yield
    clean_harness_rows("action-items")


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_action_items_seed_discovery_sync_and_custom_settings_survive(agent, tmp_path, monkeypatch):
    seed.seed_mcp_servers()
    tool = get_tool("action-items")
    assert collect_tools_from_db(agent)["action-items"]["url"] == f"{MCP_BASE}/mcp/action-items/"
    original_collect = collect_tools_from_db
    monkeypatch.setattr("services.api.models.tool.collect_tools_from_db", lambda selected: {"action-items": original_collect(selected)["action-items"]})
    destination = tmp_path / ("client.toml" if agent == "codex" else "client.json")
    destination.write_text('unrelated = "keep"\n' if agent == "codex" else '{"unrelated":"keep"}', encoding="utf-8")
    monkeypatch.setitem(AGENT_TARGETS[agent], "mcp_file", str(destination))
    monkeypatch.setattr(mcp_utils, "REPO_ROOT", tmp_path)
    assert mcp_utils.sync_mcp(agent, dry_run=False) == []
    configured = tomllib.loads(destination.read_text()) if agent == "codex" else json.loads(destination.read_text())
    assert configured["unrelated"] == "keep"
    assert configured[AGENT_TARGETS[agent]["mcp_key"]]["action-items"]["url"] == f"{MCP_BASE}/mcp/action-items/"
    update_content("tool", tool["id"], {"body": "My notes", "metadata": {"url": "http://localhost:9999/custom/", "description": "Customized"}})
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE harness_configs SET enabled=false WHERE item_type='tool' AND item_id=%s", (tool["id"],))
    customized = get_item_by_id("tool", tool["id"])
    seed.seed_mcp_servers()
    assert get_item_by_id("tool", tool["id"]) == customized


def test_action_items_seed_is_idempotent_and_tasks_never_become_harness_items():
    from services.action_items import db

    seed.seed_mcp_servers()
    first = get_tool("action-items")
    seed.seed_mcp_servers()
    assert get_tool("action-items") == first
    task = db.create({"title": "Unique task title for harness isolation"})
    try:
        assert get_tool(task["title"]) is None
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM harness_tools WHERE name='action-items'")
            assert cursor.fetchone()[0] == 1
    finally:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM action_items WHERE id=%s", (task["id"],))
