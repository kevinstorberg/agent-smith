"""Shared MCP server collection utility."""

from __future__ import annotations

import json
from pathlib import Path


def collect_mcp_servers(sources: list[str], harness_root: Path) -> dict[str, dict]:
    """
    Load *.json server definitions from source paths; later sources override earlier ones.
    Returns {server_name: fields_dict} with the 'name' key stripped out.
    """
    servers: dict[str, dict] = {}
    for source in sources:
        path = (harness_root / source).expanduser().resolve()
        if path.is_dir():
            for f in sorted(path.glob("*.json")):
                data = json.loads(f.read_text(encoding="utf-8"))
                name = data["name"]
                servers[name] = {k: v for k, v in data.items() if k != "name"}
    return servers
