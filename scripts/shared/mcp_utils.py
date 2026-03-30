from __future__ import annotations

import json
from pathlib import Path

import tomli_w

from scripts.shared.agents import AGENT_TARGETS, _read_config
from scripts.shared.env import expand_env
from scripts.shared.fs import atomic_write


def sync_mcp(agent: str, dry_run: bool) -> None:
    from services.db.harness import collect_tools_from_db

    cfg = AGENT_TARGETS[agent]
    dest = Path(cfg["mcp_file"]).expanduser()

    servers = collect_tools_from_db(agent)
    servers = {name: expand_env(srv) for name, srv in servers.items()}

    if dry_run:
        print(f"  would sync {len(servers)} server(s) -> {dest}")
        return

    data = _read_config(dest, cfg["mcp_format"]) if dest.exists() else {}
    data[cfg["mcp_key"]] = {
        name: cfg["mcp_transform"](srv) for name, srv in servers.items()
    }

    if cfg["mcp_format"] == "toml":
        _, msg = atomic_write(dest, tomli_w.dumps(data))
    else:
        _, msg = atomic_write(dest, json.dumps(data, indent=2) + "\n")
    print(f"  {msg}")
