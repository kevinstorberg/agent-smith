from __future__ import annotations

import pytest

from services.db.harness import (
    upsert_item, list_items, get_item, map_hook_event,
)
from tests.conftest import postgres_available


pytestmark = pytest.mark.skipif(
    not postgres_available(), reason="Postgres not available"
)

ALL_AGENTS = ["claude", "codex", "gemini"]
RULE_CONTENT = {"body": "## Test Rule\n* **The Rule:** Be good.", "metadata": {}}


@pytest.fixture(autouse=True)
def _clean_harness_tables():
    from services.db import get_connection, init_db
    init_db()
    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            for table in ("harness_rules", "harness_skills", "harness_tools", "harness_hooks"):
                cur.execute(f"DELETE FROM {table} WHERE name LIKE 'test_%'")


def test_upsert_rule_creates_new_row():
    row_id = upsert_item("rule", "test_dry", content=RULE_CONTENT, agents=ALL_AGENTS)
    assert row_id > 0
    row = get_item("rule", "test_dry")
    assert row["name"] == "test_dry"
    assert row["content"]["body"].startswith("## Test Rule")
    assert row["version"] == 1


def test_upsert_rule_updates_and_bumps_version():
    upsert_item("rule", "test_bump", content=RULE_CONTENT, agents=ALL_AGENTS)
    updated = {"body": "## Updated", "metadata": {}}
    upsert_item("rule", "test_bump", content=updated, agents=ALL_AGENTS)
    row = get_item("rule", "test_bump")
    assert row["version"] == 2
    assert row["content"]["body"] == "## Updated"


def test_upsert_rule_rejects_empty_name():
    with pytest.raises(AssertionError):
        upsert_item("rule", "", content=RULE_CONTENT, agents=ALL_AGENTS)


def test_list_rules_ordered_by_sort_key():
    upsert_item("rule", "test_zz", content=RULE_CONTENT, agents=ALL_AGENTS, sort_key="zz")
    upsert_item("rule", "test_aa", content=RULE_CONTENT, agents=ALL_AGENTS, sort_key="aa")
    rows = list_items("rule")
    names = [r["name"] for r in rows if r["name"].startswith("test_")]
    assert names.index("test_aa") < names.index("test_zz")


def test_list_rules_project_overrides_shared_by_name():
    upsert_item("rule", "test_override", content=RULE_CONTENT, agents=ALL_AGENTS)
    project_content = {"body": "## Project version", "metadata": {}}
    upsert_item("rule", "test_override", content=project_content, agents=ALL_AGENTS, project="myproject")
    rows = list_items("rule", project="myproject")
    match = [r for r in rows if r["name"] == "test_override"]
    assert len(match) == 1
    assert match[0]["content"]["body"] == "## Project version"


def test_list_rules_excludes_disabled():
    upsert_item("rule", "test_disabled", content=RULE_CONTENT, agents=ALL_AGENTS, enabled=False)
    rows = list_items("rule")
    names = [r["name"] for r in rows]
    assert "test_disabled" not in names


def test_list_rules_filters_by_agent():
    upsert_item("rule", "test_claude_only", content=RULE_CONTENT, agents=["claude"])
    rows = list_items("rule", agent="codex")
    names = [r["name"] for r in rows]
    assert "test_claude_only" not in names

    rows = list_items("rule", agent="claude")
    names = [r["name"] for r in rows]
    assert "test_claude_only" in names


def test_get_rule_returns_none_when_missing():
    assert get_item("rule", "test_nonexistent") is None


def test_get_rule_prefers_project_over_shared():
    upsert_item("rule", "test_pref", content=RULE_CONTENT, agents=ALL_AGENTS)
    project_content = {"body": "## Project", "metadata": {}}
    upsert_item("rule", "test_pref", content=project_content, agents=ALL_AGENTS, project="proj")
    row = get_item("rule", "test_pref", project="proj")
    assert row["content"]["body"] == "## Project"


def test_upsert_tool_stores_config_in_content_metadata():
    tool_content = {"body": "", "metadata": {"url": "https://example.com", "headers": {"X-Key": "val"}}}
    upsert_item("tool", "test_tool", content=tool_content, agents=ALL_AGENTS)
    row = get_item("tool", "test_tool")
    assert row["content"]["metadata"]["url"] == "https://example.com"


def test_upsert_hook_stores_event_and_matcher():
    hook_content = {
        "body": "",
        "metadata": {
            "event": "pre_tool_use",
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "echo ok"}],
        },
    }
    upsert_item("hook", "test_hook", content=hook_content, agents=["claude"])
    row = get_item("hook", "test_hook")
    assert row["content"]["metadata"]["event"] == "pre_tool_use"
    assert row["agents"] == ["claude"]


def test_map_hook_event_claude():
    assert map_hook_event("pre_tool_use", "claude") == "PreToolUse"
    assert map_hook_event("stop", "claude") == "Stop"


def test_map_hook_event_unsupported_agent():
    assert map_hook_event("pre_tool_use", "codex") is None
