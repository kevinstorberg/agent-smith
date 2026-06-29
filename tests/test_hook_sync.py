"""Sync-time ${REPO_ROOT} expansion for hook commands.

The host hook command is stored as ${REPO_ROOT}/scripts/audit_hook.py so one DB row
is portable across devices; sync resolves the token to each device's real repo path.
"""
from __future__ import annotations

import json

import pytest

from scripts.shared import hook_utils
from scripts.shared.agents import AGENT_TARGETS
from scripts.shared.paths import REPO_ROOT

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
    monkeypatch.setattr(hook_utils, "_in_container", lambda: False)
    result = hook_utils._expand_hook_paths(_hooks(PRE))
    assert _command(result) == f"{REPO_ROOT}/.venv/bin/python {REPO_ROOT}/scripts/audit_hook.py --phase pre"


def test_raises_in_container_without_host_repo_root(monkeypatch):
    monkeypatch.delenv("HOST_REPO_ROOT", raising=False)
    monkeypatch.setattr(hook_utils, "_in_container", lambda: True)
    with pytest.raises(RuntimeError, match="HOST_REPO_ROOT"):
        hook_utils._expand_hook_paths(_hooks(PRE))


def test_token_free_hooks_sync_in_container_without_env(monkeypatch):
    monkeypatch.delenv("HOST_REPO_ROOT", raising=False)
    monkeypatch.setattr(hook_utils, "_in_container", lambda: True)
    hooks = _hooks("/usr/bin/env python3 /opt/some_hook.py")
    assert hook_utils._expand_hook_paths(hooks) == hooks


def test_sync_hooks_writes_expanded_command(monkeypatch, tmp_path):
    dest = tmp_path / "settings.json"
    monkeypatch.setenv("HOST_REPO_ROOT", "/host/repo")
    monkeypatch.setitem(AGENT_TARGETS["claude"], "hooks_file", str(dest))
    monkeypatch.setattr(
        "services.api.models.hook.collect_hooks_from_db", lambda agent: _hooks(PRE)
    )

    hook_utils.sync_hooks("claude", dry_run=False)

    written = json.loads(dest.read_text())
    command = written["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert command == "/host/repo/.venv/bin/python /host/repo/scripts/audit_hook.py --phase pre"
    assert "${REPO_ROOT}" not in command
