from __future__ import annotations

import json
import os
from pathlib import Path

import tomli_w

from scripts.shared.agents import AGENT_TARGETS, _read_config
from scripts.shared.env import expand_env
from scripts.shared.fs import atomic_write
from scripts.shared.hook_permissions import sync_claude_hook_settings
from scripts.shared.paths import REPO_ROOT


def _expand_hook_paths(hooks: dict) -> dict:
    host_root = os.environ.get("HOST_REPO_ROOT", str(REPO_ROOT))
    return expand_env(hooks, extra={"REPO_ROOT": host_root})


def sync_hooks(agent: str, dry_run: bool) -> None:
    from services.api.models.hook import collect_hook_settings_from_db

    cfg = AGENT_TARGETS[agent]
    if "hooks_file" not in cfg:
        return

    dest = Path(cfg["hooks_file"]).expanduser()
    settings = collect_hook_settings_from_db(agent)
    hooks = _expand_hook_paths(settings.hooks)
    allowed_tools = _expand_hook_paths({"allow": settings.allowed_tools})["allow"]

    if dry_run:
        print(f"  would sync {len(hooks)} hook event(s) and {len(allowed_tools)} permission rule(s) -> {dest}")
        return

    if agent == "claude":
        changed = sync_claude_hook_settings(dest, hooks, allowed_tools)
        print(f"  {'updated' if changed else 'unchanged'}: {dest}")
        return

    data = _read_config(dest, cfg["hooks_format"]) if dest.exists() else {}
    data[cfg["hooks_key"]] = hooks

    if cfg["hooks_format"] == "toml":
        _, msg = atomic_write(dest, tomli_w.dumps(data))
    else:
        _, msg = atomic_write(dest, json.dumps(data, indent=2) + "\n")
    print(f"  {msg}")
