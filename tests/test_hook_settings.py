from __future__ import annotations

from copy import deepcopy

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


@pytest.mark.parametrize("default_model", ["haiku", "future/provider-model"])
def test_compiler_normalizes_legacy_model_without_mutating_stored_metadata(default_model):
    handlers = [
        {"type": "agent", "prompt": "Capture", "timeout": 120},
        {"type": "prompt", "prompt": "Review"},
        {"type": "agent", "model": "custom/provider-model", "prompt": "Explicit"},
        {"type": "command", "command": "echo capture"},
        {"type": "http", "url": "https://example.invalid/hook"},
    ]
    row = _row(model=default_model, hooks=handlers)
    original = deepcopy(row)
    settings = hook.compile_hook_settings([row], "claude")
    normalized = settings.hooks["Stop"][0]["hooks"]
    assert [handler.get("model") for handler in normalized] == [default_model, default_model, "custom/provider-model", None, None]
    assert all(result is not source for result, source in zip(normalized, handlers))
    assert normalized[0]["timeout"] == 120
    assert row == original


@pytest.mark.parametrize("model", [None, "", " \t", 1, False, [], {}])
def test_compiler_rejects_invalid_legacy_model_with_its_field(model):
    with pytest.raises(ValueError, match=r"Hook capture: metadata\.model must be a nonblank string"):
        hook.compile_hook_settings([_row(model=model)], "claude")


@pytest.mark.parametrize("handler_type", ["command", "http", "unknown"])
def test_compiler_rejects_explicit_model_on_non_ai_handlers(handler_type):
    with pytest.raises(ValueError, match=r"Hook capture: metadata\.hooks\[0\]\.model is supported only for prompt or agent hooks"):
        hook.compile_hook_settings([_row(hooks=[{"type": handler_type, "model": "haiku"}])], "claude")


@pytest.mark.parametrize("handlers", [[{"type": "command"}], [{"type": "http"}], [{"type": "command"}, {"type": "http"}]])
def test_compiler_rejects_legacy_default_without_an_ai_recipient(handlers):
    with pytest.raises(ValueError, match=r"Hook capture: metadata\.model requires a prompt or agent handler"):
        hook.compile_hook_settings([_row(model="haiku", hooks=handlers)], "claude")


@pytest.mark.parametrize("agent", ["codex", "gemini"])
def test_irrelevant_event_is_filtered_before_legacy_model_normalization(agent):
    settings = hook.compile_hook_settings([_row(event="notification", model=None, hooks="invalid", permissions={"deny": [SEARCH]})], agent)
    assert settings == hook.HookSettings({}, [])


@pytest.mark.parametrize("content", [None, [], "invalid"])
def test_compiler_rejects_invalid_content_with_item_and_field(content):
    with pytest.raises(ValueError, match=r"Hook capture: content must be an object"):
        hook.compile_hook_settings([{"name": "capture", "content": content}], "claude")


@pytest.mark.parametrize("metadata", [None, [], "invalid"])
def test_compiler_rejects_invalid_metadata_with_item_and_field(metadata):
    with pytest.raises(ValueError, match=r"Hook capture: metadata must be an object"):
        hook.compile_hook_settings([{"name": "capture", "content": {"metadata": metadata}}], "claude")


@pytest.mark.parametrize("handlers", [None, {}, "invalid", [None]])
def test_compiler_rejects_invalid_handler_collection_with_item_and_field(handlers):
    with pytest.raises(ValueError, match=r"Hook capture: metadata\.hooks must be a list of objects"):
        hook.compile_hook_settings([_row(hooks=handlers)], "claude")


@pytest.mark.parametrize("permissions", [None, [], {"allow": "bad"}, {"allow": [""]}, {"allow": [1]}, {"deny": [SEARCH]}])
def test_compiler_rejects_invalid_permission_metadata(permissions):
    with pytest.raises(ValueError):
        hook.compile_hook_settings([_row(permissions=permissions)], "claude")


@pytest.mark.parametrize("rule", ["mcp__memory__*", "mcp__memory", "Bash(*)", "Bash( *)", "Bash(python *)", "Bash(/usr/bin/python *)", "Bash(/bin/sh -c *)", "Bash(/python; other *)", "Bash(/python $(other) *)", "Read"])
def test_compiler_rejects_broad_or_ambiguous_permission_rules(rule):
    with pytest.raises(ValueError, match="exact MCP tool or a fixed Python"):
        hook.compile_hook_settings([_row(permissions={"allow": [rule]})], "claude")


@pytest.mark.parametrize("model", [None, "", " \t", 1, False])
@pytest.mark.parametrize("legacy_default", [{}, {"model": "haiku"}])
def test_compiler_rejects_invalid_nested_model_without_default_fallback(model, legacy_default):
    with pytest.raises(ValueError, match="model must be a nonblank string"):
        hook.compile_hook_settings([_row(hooks=[{"type": "agent", "model": model}], **legacy_default)], "claude")


def test_permissions_are_claude_only_and_other_agents_still_map_hooks():
    with pytest.raises(ValueError, match="only for Claude"):
        hook.compile_hook_settings([_row(permissions={"allow": [SEARCH]})], "codex")
    assert "stop" in hook.compile_hook_settings([_row()], "codex").hooks


def test_empty_handler_group_and_empty_collection_are_valid():
    assert hook.compile_hook_settings([_row(hooks=[])], "claude").hooks == {"Stop": [{"matcher": "*", "hooks": []}]}
    assert hook.compile_hook_settings([_row(hooks=[], model="haiku", permissions={"allow": [SEARCH]})], "claude") == hook.HookSettings(
        {"Stop": [{"matcher": "*", "hooks": []}]}, []
    )
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
