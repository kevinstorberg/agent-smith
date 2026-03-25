from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from scripts.shared.env import expand_env
from scripts.shared.fs import atomic_write


def collect_mcp_servers(sources: list[str], harness_root: Path) -> dict[str, dict]:
    """
    Load *.json server definitions from source paths; later sources override earlier ones.
    Returns {server_name: fields_dict} with the 'name' key stripped out.
    Expands ${VAR} references using the process environment.
    """
    servers: dict[str, dict] = {}
    for source in sources:
        path = (harness_root / source).expanduser().resolve()
        if path.is_dir():
            for f in sorted(path.glob("*.json")):
                data = json.loads(f.read_text(encoding="utf-8"))
                name = data["name"]
                fields = {k: v for k, v in data.items() if k != "name"}
                servers[name] = expand_env(fields)
    return {
        name: srv for name, srv in servers.items()
        if os.environ.get(f"{name}_ENABLED", "").lower() != "false"
    }


def sync_mcp_to_file(
    harness_root: Path,
    config: dict,
    dry_run: bool,
    read_file: Callable[[Path], dict],
    write_file: Callable[[Path, dict], tuple[bool, str]],
    transform_entry: Callable[[dict], dict],
    dest_key: str,
) -> None:
    """Shared MCP sync logic. Each agent provides its own transform and serializer."""
    for target in config.get("targets", []):
        dest = Path(target["path"]).expanduser()
        servers = collect_mcp_servers(target.get("merge", []), harness_root)
        if dry_run:
            print(f"  would sync {len(servers)} server(s) -> {dest}")
            continue
        data = read_file(dest) if dest.exists() else {}
        data[dest_key] = {name: transform_entry(srv) for name, srv in servers.items()}
        _, msg = write_file(dest, data)
        print(f"  {msg}")


def sync_mcp_from_db(
    agent: str,
    config: dict,
    dry_run: bool,
    read_file: Callable[[Path], dict],
    write_file: Callable[[Path, dict], tuple[bool, str]],
    transform_entry: Callable[[dict], dict],
    dest_key: str,
    project: str | None = None,
) -> None:
    from services.db.harness import collect_tools_from_db
    servers = collect_tools_from_db(agent, project=project)
    servers = {
        name: expand_env(srv) for name, srv in servers.items()
        if os.environ.get(f"{name}_ENABLED", "").lower() != "false"
    }
    for target in config.get("targets", []):
        dest = Path(target["path"]).expanduser()
        if dry_run:
            print(f"  would sync {len(servers)} server(s) -> {dest}")
            continue
        data = read_file(dest) if dest.exists() else {}
        data[dest_key] = {name: transform_entry(srv) for name, srv in servers.items()}
        _, msg = write_file(dest, data)
        print(f"  {msg}")
