from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Callable

import tomli_w

from scripts.shared.env import expand_env
from scripts.shared.fs import atomic_write


def collect_mcp_servers(sources: list[str], harness_root: Path) -> dict[str, dict]:
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


# --- Agent-specific MCP configuration ---

def _transform_claude(srv: dict) -> dict:
    entry = {"type": "http", "url": srv["url"]}
    if "headers" in srv:
        entry["headers"] = srv["headers"]
    if "oauth" in srv:
        entry["oauth"] = srv["oauth"]
    return entry


def _transform_codex(srv: dict) -> dict:
    entry = {"url": srv["url"]}
    if "headers" in srv:
        entry["headers"] = srv["headers"]
    return entry


def _transform_gemini(srv: dict) -> dict:
    entry = {"httpUrl": srv["url"]}
    if "headers" in srv:
        entry["headers"] = srv["headers"]
    return entry


def _read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _write_json(p: Path, d: dict) -> tuple[bool, str]:
    return atomic_write(p, json.dumps(d, indent=2) + "\n")


def _read_toml(p: Path) -> dict:
    return tomllib.loads(p.read_text(encoding="utf-8"))


def _write_toml(p: Path, d: dict) -> tuple[bool, str]:
    return atomic_write(p, tomli_w.dumps(d))


MCP_AGENT_CONFIG = {
    "claude": {
        "dest_key": "mcpServers",
        "read_file": _read_json,
        "write_file": _write_json,
        "transform": _transform_claude,
    },
    "codex": {
        "dest_key": "mcp_servers",
        "read_file": _read_toml,
        "write_file": _write_toml,
        "transform": _transform_codex,
    },
    "gemini": {
        "dest_key": "mcpServers",
        "read_file": _read_json,
        "write_file": _write_json,
        "transform": _transform_gemini,
    },
}


def sync_mcp(harness_root: Path, config: dict, dry_run: bool, source: str, agent: str) -> None:
    cfg = MCP_AGENT_CONFIG[agent]
    kwargs = dict(
        read_file=cfg["read_file"],
        write_file=cfg["write_file"],
        transform_entry=cfg["transform"],
        dest_key=cfg["dest_key"],
    )
    if source == "db":
        sync_mcp_from_db(agent, config, dry_run, **kwargs)
    else:
        sync_mcp_to_file(harness_root, config, dry_run, **kwargs)
