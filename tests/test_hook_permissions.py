from __future__ import annotations

import json

import pytest

from scripts.shared import hook_permissions


SEARCH = "mcp__memory__memory_search"
ADD = "mcp__memory__memory_add"
HOOKS = {"Stop": [{"matcher": "*", "hooks": [{"type": "agent", "model": "haiku", "prompt": "Capture memory"}]}]}


def _read(path):
    return json.loads(path.read_text())


def test_managed_grants_preserve_unrelated_settings_and_preexisting_rule(tmp_path):
    path = tmp_path / "settings.json"
    existing = {
        "theme": "dark",
        "permissions": {"allow": ["Bash(ls)", SEARCH], "deny": ["Bash(rm *)"], "ask": ["Write"], "defaultMode": "auto"},
    }
    path.write_text(json.dumps(existing))
    assert hook_permissions.sync_claude_hook_settings(path, HOOKS, [SEARCH, ADD, ADD])
    updated = _read(path)
    assert updated == {**existing, "hooks": HOOKS, "permissions": {**existing["permissions"], "allow": ["Bash(ls)", SEARCH, ADD]}}
    state = hook_permissions.ownership_path(path)
    assert _read(state) == {"version": 1, "owned_rules": [ADD]}

    assert hook_permissions.sync_claude_hook_settings(path, {}, [])
    assert _read(path) == {**existing, "hooks": {}}
    assert _read(state) == {"version": 1, "owned_rules": []}


def test_idempotent_sync_and_shared_grants(tmp_path):
    path = tmp_path / "settings.json"
    hook_permissions.sync_claude_hook_settings(path, HOOKS, [SEARCH, ADD])
    state = hook_permissions.ownership_path(path)
    before = path.stat().st_mtime_ns, state.stat().st_mtime_ns
    assert not hook_permissions.sync_claude_hook_settings(path, HOOKS, [SEARCH, ADD])
    assert before == (path.stat().st_mtime_ns, state.stat().st_mtime_ns)
    hook_permissions.sync_claude_hook_settings(path, HOOKS, [SEARCH])
    assert _read(path)["permissions"]["allow"] == [SEARCH]
    assert _read(state)["owned_rules"] == [SEARCH]


@pytest.mark.parametrize("failure_stage", ["settings", "finalize"])
def test_interrupted_transaction_recovers_and_revokes_introduced_grants(tmp_path, monkeypatch, failure_stage):
    path = tmp_path / "settings.json"
    state = hook_permissions.ownership_path(path)
    path.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}, "theme": "dark"}))
    write = hook_permissions.atomic_write_json

    def interrupt(destination, value):
        if (failure_stage == "settings" and destination == path) or (
            failure_stage == "finalize" and destination == state and "pending" not in value
        ):
            raise OSError("synthetic interruption")
        return write(destination, value)

    monkeypatch.setattr(hook_permissions, "atomic_write_json", interrupt)
    with pytest.raises(OSError, match="synthetic interruption"):
        hook_permissions.sync_claude_hook_settings(path, HOOKS, [SEARCH])
    assert "pending" in _read(state)
    assert SEARCH not in state.read_text().split('"pending"')[0]
    monkeypatch.setattr(hook_permissions, "atomic_write_json", write)
    hook_permissions.sync_claude_hook_settings(path, {}, [])
    assert _read(path) == {"permissions": {"allow": ["Bash(ls)"]}, "theme": "dark", "hooks": {}}
    assert _read(state) == {"version": 1, "owned_rules": []}


def test_interrupted_sync_refuses_divergent_permissions_without_printing_rules(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    state = hook_permissions.ownership_path(path)
    write = hook_permissions.atomic_write_json

    def interrupt(destination, value):
        if destination == path:
            raise OSError("synthetic interruption")
        return write(destination, value)

    monkeypatch.setattr(hook_permissions, "atomic_write_json", interrupt)
    with pytest.raises(OSError):
        hook_permissions.sync_claude_hook_settings(path, HOOKS, [SEARCH])
    private_rule = "Bash(secret-value)"
    path.write_text(json.dumps({"permissions": {"allow": [private_rule]}}))
    original = path.read_bytes()
    monkeypatch.setattr(hook_permissions, "atomic_write_json", write)
    with pytest.raises(RuntimeError, match="interrupted hook Sync") as error:
        hook_permissions.sync_claude_hook_settings(path, HOOKS, [SEARCH])
    assert private_rule not in str(error.value)
    assert private_rule not in state.read_text()
    assert path.read_bytes() == original


def test_sync_refuses_concurrent_settings_edit(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    state = hook_permissions.ownership_path(path)
    path.write_text(json.dumps({"theme": "dark"}))
    write = hook_permissions.atomic_write_json

    def edit_after_intent(destination, value):
        result = write(destination, value)
        if destination == state and "pending" in value:
            path.write_text(json.dumps({"theme": "light"}))
        return result

    monkeypatch.setattr(hook_permissions, "atomic_write_json", edit_after_intent)
    with pytest.raises(RuntimeError, match="no settings were overwritten"):
        hook_permissions.sync_claude_hook_settings(path, HOOKS, [SEARCH])
    assert _read(path) == {"theme": "light"}


@pytest.mark.parametrize("settings", [{"permissions": []}, {"permissions": {"allow": "bad"}}, {"permissions": {"allow": [1]}}])
def test_invalid_permissions_are_not_overwritten(tmp_path, settings):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings))
    original = path.read_bytes()
    with pytest.raises(ValueError):
        hook_permissions.sync_claude_hook_settings(path, HOOKS, [SEARCH])
    assert path.read_bytes() == original


def test_corrupt_ownership_refuses_to_forget_grants(tmp_path):
    path = tmp_path / "settings.json"
    hook_permissions.sync_claude_hook_settings(path, HOOKS, [SEARCH])
    hook_permissions.ownership_path(path).write_text("broken JSON")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="ownership state"):
        hook_permissions.sync_claude_hook_settings(path, {}, [])
    assert path.read_bytes() == original


def test_empty_hooks_do_not_create_unnecessary_permission_block(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hooks": HOOKS, "theme": "dark"}))
    hook_permissions.sync_claude_hook_settings(path, {}, [])
    assert _read(path) == {"hooks": {}, "theme": "dark"}


def test_malformed_settings_fail_before_ownership_or_settings_write(tmp_path, monkeypatch):
    from scripts.shared import agents

    path = tmp_path / "settings.json"
    path.write_text('{"permissions": broken JSON')
    original = path.read_bytes()
    read = agents.read_with_retry
    monkeypatch.setattr(agents, "read_with_retry", lambda file, fmt: read(file, fmt, max_attempts=1, backoff=0))
    with pytest.raises(agents.ConfigUnreadableError):
        hook_permissions.sync_claude_hook_settings(path, HOOKS, [SEARCH])
    assert path.read_bytes() == original
    assert not hook_permissions.ownership_path(path).exists()


def test_compiled_helper_permissions_keep_quoted_spaces(tmp_path):
    path = tmp_path / "settings.json"
    permission = 'Bash("/fixed directory/.venv/bin/python" "/fixed directory/scripts/claude_memory_context.py" *)'
    hook_permissions.sync_claude_hook_settings(path, HOOKS, [permission])
    assert _read(path)["permissions"]["allow"] == [permission]
