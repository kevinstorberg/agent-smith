"""Sync-time ${REPO_ROOT} expansion for hook commands.

The host hook command is stored as ${REPO_ROOT}/scripts/audit_hook.py so one DB row
is portable across devices; sync resolves the token to each device's real repo path.
"""
from __future__ import annotations

import json

from scripts.shared import hook_utils
from scripts.shared.agents import AGENT_TARGETS
from scripts.shared.paths import REPO_ROOT
from services.api.models.hook import HookSettings

PRE = "${REPO_ROOT}/.venv/bin/python ${REPO_ROOT}/scripts/audit_hook.py --phase pre"


def _hooks(command: str) -> dict:
    return {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": command}]}]}


def _command(hooks: dict) -> str:
    return hooks["PreToolUse"][0]["hooks"][0]["command"]


def test_expands_to_host_repo_root_when_injected(monkeypatch):
    monkeypatch.setenv("HOST_REPO_ROOT", "/host/repo")
    result = hook_utils._expand_hook_paths(_hooks(PRE))
    assert _command(result) == "/host/repo/.venv/bin/python /host/repo/scripts/audit_hook.py --phase pre"


def test_falls_back_to_repo_root_on_host(monkeypatch):
    monkeypatch.delenv("HOST_REPO_ROOT", raising=False)
    result = hook_utils._expand_hook_paths(_hooks(PRE))
    assert _command(result) == f"{REPO_ROOT}/.venv/bin/python {REPO_ROOT}/scripts/audit_hook.py --phase pre"


def test_token_free_hooks_are_unchanged(monkeypatch):
    monkeypatch.delenv("HOST_REPO_ROOT", raising=False)
    hooks = _hooks("/usr/bin/env python3 /opt/some_hook.py")
    assert hook_utils._expand_hook_paths(hooks) == hooks


def test_sync_hooks_writes_expanded_command(monkeypatch, tmp_path):
    dest = tmp_path / "settings.json"
    monkeypatch.setenv("HOST_REPO_ROOT", "/host/repo")
    monkeypatch.setitem(AGENT_TARGETS["claude"], "hooks_file", str(dest))
    monkeypatch.setattr(
        "services.api.models.hook.collect_hook_settings_from_db", lambda agent: HookSettings(_hooks(PRE), [])
    )

    hook_utils.sync_hooks("claude", dry_run=False)

    written = json.loads(dest.read_text())
    command = written["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert command == "/host/repo/.venv/bin/python /host/repo/scripts/audit_hook.py --phase pre"
    assert "${REPO_ROOT}" not in command


def test_sync_hooks_delivers_model_and_expanded_permissions(tmp_path, monkeypatch):
    dest = tmp_path / "settings.json"
    hooks = {"Stop": [{"matcher": "*", "hooks": [{"type": "agent", "model": "haiku", "prompt": "Capture", "timeout": 120}]}]}
    permission = "Bash(${REPO_ROOT}/.venv/bin/python ${REPO_ROOT}/scripts/claude_memory_context.py *)"
    monkeypatch.setenv("HOST_REPO_ROOT", "/host/repo")
    monkeypatch.setitem(AGENT_TARGETS["claude"], "hooks_file", str(dest))
    monkeypatch.setattr("services.api.models.hook.collect_hook_settings_from_db", lambda agent: HookSettings(hooks, [permission]))
    hook_utils.sync_hooks("claude", False)
    written = json.loads(dest.read_text())
    assert written["hooks"]["Stop"][0]["hooks"][0]["model"] == "haiku"
    assert written["permissions"]["allow"] == ["Bash(/host/repo/.venv/bin/python /host/repo/scripts/claude_memory_context.py *)"]


def test_sync_empty_hooks_clears_previous_hooks_and_owned_grants(tmp_path, monkeypatch):
    dest = tmp_path / "settings.json"
    monkeypatch.setitem(AGENT_TARGETS["claude"], "hooks_file", str(dest))
    monkeypatch.setattr("services.api.models.hook.collect_hook_settings_from_db", lambda agent: HookSettings(_hooks(PRE), ["mcp__memory__memory_search"]))
    hook_utils.sync_hooks("claude", False)
    monkeypatch.setattr("services.api.models.hook.collect_hook_settings_from_db", lambda agent: HookSettings({}, []))
    hook_utils.sync_hooks("claude", False)
    written = json.loads(dest.read_text())
    assert written["hooks"] == {}
    assert written["permissions"]["allow"] == []


def test_dry_run_creates_no_settings_lock_or_journal(tmp_path, monkeypatch):
    dest = tmp_path / "not-created" / "settings.json"
    monkeypatch.setitem(AGENT_TARGETS["claude"], "hooks_file", str(dest))
    monkeypatch.setattr("services.api.models.hook.collect_hook_settings_from_db", lambda agent: HookSettings(_hooks(PRE), ["mcp__memory__memory_search"]))
    hook_utils.sync_hooks("claude", True)
    assert not list(tmp_path.iterdir())


def test_nonclaude_sync_preserves_toml_and_removes_stale_hooks(tmp_path, monkeypatch):
    import tomllib

    dest = tmp_path / "config.toml"
    dest.write_text('model = "unchanged"\n[hooks]\nold = []\n')
    monkeypatch.setitem(AGENT_TARGETS["codex"], "hooks_file", str(dest))
    monkeypatch.setattr("services.api.models.hook.collect_hook_settings_from_db", lambda agent: HookSettings({}, []))
    hook_utils.sync_hooks("codex", False)
    assert tomllib.loads(dest.read_text()) == {"model": "unchanged", "hooks": {}}


def test_single_item_hook_sync_rebuilds_all_active_hooks(tmp_path, monkeypatch):
    from scripts.shared import fs
    from services.api.models import hook

    selected = {"id": 83, "name": "capture", "agents": ["claude"]}
    rows = [{"name": name, "content": {"body": "", "metadata": {
        "event": "stop", "hooks": [{"type": "agent", "model": "haiku", "prompt": name}],
        "permissions": {"allow": [f"mcp__memory__{tool}"]},
    }}} for name, tool in [("capture", "memory_search"), ("other", "memory_list")]]
    dest = tmp_path / "settings.json"
    monkeypatch.setitem(AGENT_TARGETS["claude"], "hooks_file", str(dest))
    monkeypatch.setattr("services.api.models.shared.harness.get_item_by_id", lambda *args: selected)
    monkeypatch.setattr(hook, "list_items", lambda *args, **kwargs: rows)
    result = fs.sync_item("hook", 83)
    assert result["success"]
    written = json.loads(dest.read_text())
    assert len(written["hooks"]["Stop"]) == 2
    assert written["permissions"]["allow"] == ["mcp__memory__memory_search", "mcp__memory__memory_list"]
