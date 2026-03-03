"""Sync MCP servers to Codex: merge mcp_servers table into ~/.codex/config.toml."""

from __future__ import annotations

import tomllib
import tomli_w
from pathlib import Path

from scripts.shared.fs import atomic_write
from scripts.shared.mcp_utils import collect_mcp_servers


def main(harness_root: Path, config: dict, dry_run: bool) -> None:
    for target in config.get("targets", []):
        dest = Path(target["path"]).expanduser()
        servers = collect_mcp_servers(target.get("merge", []), harness_root)
        if dry_run:
            print(f"  would sync {len(servers)} server(s) → {dest}")
            continue
        data = tomllib.loads(dest.read_text(encoding="utf-8")) if dest.exists() else {}
        data["mcp_servers"] = {name: {"url": srv["url"]} for name, srv in servers.items()}
        _, msg = atomic_write(dest, tomli_w.dumps(data))
        print(f"  {msg}")
