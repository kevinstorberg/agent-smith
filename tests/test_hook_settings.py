from __future__ import annotations

import pytest

from services.api.models import hook


SEARCH = "mcp__memory__memory_search"
PREFIX = "Bash(${REPO_ROOT}/.venv/bin/python ${REPO_ROOT}/scripts/claude_memory_context.py *)"


def _row(name="capture", **metadata):
    return {"name": name, "content": {"body": "", "metadata": {"event": "stop", "matcher": "*", "hooks": [{"type": "agent", "model": "haiku", "prompt": "Capture"}], **metadata}}}


def test_compiler_preserves_nested_model_and_collects_shared_permissions_once():
    rows = [_row(permissions={"allow": [SEARCH, PREFIX]}), _row("other", permissions={"allow": [SEARCH]})]
    settings = hook.compile_hook_settings(rows, "claude")
    assert settings.allowed_tools == [SEARCH, PREFIX]
    assert len(settings.hooks["Stop"]) == 2
    assert settings.hooks["Stop"][0]["hooks"][0]["model"] == "haiku"
    assert "permissions" not in settings.hooks["Stop"][0]


def test_combined_collector_reads_one_snapshot_and_legacy_collector_returns_hooks(monkeypatch):
    calls = []
    rows = [_row(permissions={"allow": [SEARCH]})]

    def list_items(item_type, **kwargs):
        calls.append((item_type, kwargs))
        return rows

    monkeypatch.setattr(hook, "list_items", list_items)
    result = hook.collect_hook_settings_from_db("claude")
    assert len(calls) == 1
    assert calls[0] == ("hook", {"project": None, "agent": "claude"})
    assert hook.collect_hooks_from_db("claude") == result.hooks


def test_compiler_rejects_misplaced_model_with_item_and_remediation():
    with pytest.raises(ValueError, match=r"capture: move metadata.model into each metadata.hooks entry"):
        hook.compile_hook_settings([_row(model="haiku")], "claude")


@pytest.mark.parametrize("permissions", [None, [], {"allow": "bad"}, {"allow": [""]}, {"allow": [1]}, {"deny": [SEARCH]}])
def test_compiler_rejects_invalid_permission_metadata(permissions):
    with pytest.raises(ValueError):
        hook.compile_hook_settings([_row(permissions=permissions)], "claude")


@pytest.mark.parametrize("rule", ["mcp__memory__*", "mcp__memory", "Bash(*)", "Bash( *)", "Bash(python *)", "Bash(/usr/bin/python *)", "Bash(/bin/sh -c *)", "Bash(/python; other *)", "Bash(/python $(other) *)", "Read"])
def test_compiler_rejects_broad_or_ambiguous_permission_rules(rule):
    with pytest.raises(ValueError, match="exact MCP tool or a fixed Python"):
        hook.compile_hook_settings([_row(permissions={"allow": [rule]})], "claude")


@pytest.mark.parametrize("model", [None, "", 1])
def test_compiler_rejects_invalid_nested_model(model):
    with pytest.raises(ValueError, match="model must be a nonblank string"):
        hook.compile_hook_settings([_row(hooks=[{"type": "agent", "model": model}])], "claude")


def test_permissions_are_claude_only_and_other_agents_still_map_hooks():
    with pytest.raises(ValueError, match="only for Claude"):
        hook.compile_hook_settings([_row(permissions={"allow": [SEARCH]})], "codex")
    assert "stop" in hook.compile_hook_settings([_row()], "codex").hooks


def test_empty_handler_group_and_empty_collection_are_valid():
    assert hook.compile_hook_settings([_row(hooks=[])], "claude").hooks == {"Stop": [{"matcher": "*", "hooks": []}]}
    assert hook.compile_hook_settings([], "claude").hooks == {}


@pytest.mark.parametrize("event", [{}, 1, None, ""])
def test_invalid_canonical_event_names_its_field(event):
    with pytest.raises(ValueError, match="Hook capture: metadata.event must be a nonblank canonical event name"):
        hook.compile_hook_settings([_row(event=event)], "claude")


def test_empty_handlers_release_grants_but_preserve_other_active_hook_grants():
    empty = _row(hooks=[], permissions={"allow": [SEARCH, PREFIX]})
    assert hook.compile_hook_settings([empty], "claude").allowed_tools == []
    active = _row("other", permissions={"allow": [SEARCH]})
    assert hook.compile_hook_settings([empty, active], "claude").allowed_tools == [SEARCH]
    assert hook.compile_hook_settings([_row(event="notification")], "codex").hooks == {}


def test_compiler_accepts_quoted_helper_paths_and_rejects_unsupported_agents():
    permission = 'Bash("${REPO_ROOT}/.venv/bin/python" "${REPO_ROOT}/scripts/claude_memory_context.py" *)'
    assert hook.compile_hook_settings([_row(permissions={"allow": [permission]})], "claude").allowed_tools == [permission]
    with pytest.raises(ValueError, match="Unsupported hook agent"):
        hook.compile_hook_settings([], "unsupported")
