"""Sync MCP servers to Gemini: merge mcpServers key into ~/.gemini/settings.json."""

from __future__ import annotations

import json
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
        data = json.loads(dest.read_text(encoding="utf-8")) if dest.exists() else {}
        data["mcpServers"] = {
            name: {"httpUrl": srv["url"]} for name, srv in servers.items()
        }
        _, msg = atomic_write(dest, json.dumps(data, indent=2) + "\n")
        print(f"  {msg}")
