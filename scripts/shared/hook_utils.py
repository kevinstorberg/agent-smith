from __future__ import annotations

import json
from pathlib import Path

import tomli_w

from scripts.shared.agents import AGENT_TARGETS, _read_config
from scripts.shared.fs import atomic_write


def sync_hooks(agent: str, dry_run: bool) -> None:
    from services.api.models.hook import collect_hooks_from_db

    cfg = AGENT_TARGETS[agent]
    if "hooks_file" not in cfg:
        return

    dest = Path(cfg["hooks_file"]).expanduser()
    hooks = collect_hooks_from_db(agent)

    if dry_run:
        print(f"  would sync {len(hooks)} hook event(s) -> {dest}")
        return

    if not hooks:
        print("  no hooks to sync")
        return

    data = _read_config(dest, cfg["hooks_format"]) if dest.exists() else {}
    data[cfg["hooks_key"]] = hooks

    if cfg["hooks_format"] == "toml":
        _, msg = atomic_write(dest, tomli_w.dumps(data))
    else:
        _, msg = atomic_write(dest, json.dumps(data, indent=2) + "\n")
    print(f"  {msg}")
