from __future__ import annotations

import json
import os
from pathlib import Path

import tomli_w

from scripts.shared.agents import AGENT_TARGETS, _read_config
from scripts.shared.env import expand_env
from scripts.shared.fs import atomic_write
from scripts.shared.paths import REPO_ROOT


def _in_container() -> bool:
    return Path("/.dockerenv").exists()


def _expand_hook_paths(hooks: dict) -> dict:
    """Expand ${REPO_ROOT} (and any ${VAR}) in hook commands to this device's paths.

    Sync runs inside the container, where REPO_ROOT is the container path (/app), so
    the host repo path is injected as HOST_REPO_ROOT. Run directly on the host (no
    container), REPO_ROOT is already the real path. Fail loudly rather than write a
    container path into the host's settings when a hook needs the token but the env
    is missing in a not-yet-recreated container.
    """
    host_root = os.environ.get("HOST_REPO_ROOT")
    if host_root is None:
        if "${REPO_ROOT}" in json.dumps(hooks) and _in_container():
            raise RuntimeError(
                "HOST_REPO_ROOT is unset but sync is running in a container; recreate "
                "the app container (docker compose up -d) so hook ${REPO_ROOT} resolves "
                "to the host repo path instead of /app."
            )
        host_root = str(REPO_ROOT)
    return expand_env(hooks, extra={"REPO_ROOT": host_root})


def sync_hooks(agent: str, dry_run: bool) -> None:
    from services.api.models.hook import collect_hooks_from_db

    cfg = AGENT_TARGETS[agent]
    if "hooks_file" not in cfg:
        return

    dest = Path(cfg["hooks_file"]).expanduser()
    hooks = _expand_hook_paths(collect_hooks_from_db(agent))

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
