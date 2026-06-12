from __future__ import annotations

import pytest

from services.api.models.shared.harness import upsert_item, list_items, list_items_summary, get_item
from services.api.models.hook import map_hook_event
from services.config import ALL_AGENTS
from tests.conftest import harness_cleanup

RULE_CONTENT = {"body": "## Test Rule\n* **The Rule:** Be good.", "metadata": {}}

_clean = harness_cleanup("test_%")


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


def test_upsert_preserves_virtual_agent_assignments():
    upsert_item("rule", "test_virtual", content=RULE_CONTENT, agents=[*ALL_AGENTS, "opinion"])
    upsert_item("rule", "test_virtual", content=RULE_CONTENT, agents=ALL_AGENTS)
    row = get_item("rule", "test_virtual")
    assert row["version"] == 2
    assert "opinion" in row["agents"]
    assert set(ALL_AGENTS) <= set(row["agents"])


def test_upsert_does_not_add_virtual_agents_to_new_items():
    upsert_item("rule", "test_no_virtual", content=RULE_CONTENT, agents=ALL_AGENTS)
    row = get_item("rule", "test_no_virtual")
    assert "opinion" not in row["agents"]


def test_update_metadata_still_removes_virtual_agents():
    from services.api.models.shared.harness import update_metadata

    upsert_item("rule", "test_virtual_rm", content=RULE_CONTENT, agents=[*ALL_AGENTS, "opinion"])
    row = get_item("rule", "test_virtual_rm")
    update_metadata("rule", row["id"], agents=ALL_AGENTS)
    row = get_item("rule", "test_virtual_rm")
    assert "opinion" not in row["agents"]


def test_list_rules_ordered_by_sort_key():
    upsert_item("rule", "test_zz", content=RULE_CONTENT, agents=ALL_AGENTS, sort_key=20)
    upsert_item("rule", "test_aa", content=RULE_CONTENT, agents=ALL_AGENTS, sort_key=10)
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


def test_list_rules_without_project_filter_includes_project_scoped_rows():
    upsert_item("rule", "test_global_visible", content=RULE_CONTENT, agents=ALL_AGENTS)
    upsert_item("rule", "test_project_visible", content=RULE_CONTENT, agents=ALL_AGENTS, project="project-a")

    rows = list_items("rule")
    rows_by_name = {r["name"]: r for r in rows}

    assert rows_by_name["test_global_visible"]["project"] is None
    assert rows_by_name["test_project_visible"]["project"] == "project-a"


def test_list_rules_project_filter_excludes_other_projects():
    upsert_item("rule", "test_global_scoped", content=RULE_CONTENT, agents=ALL_AGENTS)
    upsert_item("rule", "test_project_a", content=RULE_CONTENT, agents=ALL_AGENTS, project="project-a")
    upsert_item("rule", "test_project_b", content=RULE_CONTENT, agents=ALL_AGENTS, project="project-b")

    rows = list_items("rule", project="project-a")
    names = {r["name"] for r in rows}

    assert "test_global_scoped" in names
    assert "test_project_a" in names
    assert "test_project_b" not in names


def test_list_items_summary_without_project_filter_includes_project_scoped_rows():
    upsert_item("rule", "test_summary_global", content=RULE_CONTENT, agents=ALL_AGENTS)
    upsert_item("rule", "test_summary_project", content=RULE_CONTENT, agents=ALL_AGENTS, project="project-a")

    rows = list_items_summary("rule")
    rows_by_name = {r["name"]: r for r in rows}

    assert rows_by_name["test_summary_global"]["project"] is None
    assert rows_by_name["test_summary_project"]["project"] == "project-a"


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


def test_map_hook_event_codex():
    assert map_hook_event("pre_tool_use", "codex") == "pre_tool_use"
    assert map_hook_event("stop", "codex") == "stop"


def test_map_hook_event_gemini():
    assert map_hook_event("pre_tool_use", "gemini") == "preToolUse"
    assert map_hook_event("stop", "gemini") == "stop"


def test_map_hook_event_unsupported_agent():
    assert map_hook_event("pre_tool_use", "unsupported_agent") is None
