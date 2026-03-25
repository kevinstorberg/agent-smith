from __future__ import annotations

import json
from pathlib import Path

from scripts.shared.fs import atomic_write
from scripts.shared.mcp_utils import sync_mcp_to_file, sync_mcp_from_db


def _transform(srv: dict) -> dict:
    entry = {"type": "http", "url": srv["url"]}
    if "headers" in srv:
        entry["headers"] = srv["headers"]
    if "oauth" in srv:
        entry["oauth"] = srv["oauth"]
    return entry


def main(harness_root: Path, config: dict, dry_run: bool, source: str = "filesystem", agent: str = "claude", **_) -> None:
    kwargs = dict(
        read_file=lambda p: json.loads(p.read_text(encoding="utf-8")),
        write_file=lambda p, d: atomic_write(p, json.dumps(d, indent=2) + "\n"),
        transform_entry=_transform,
        dest_key="mcpServers",
    )
    if source == "db":
        sync_mcp_from_db(agent, config, dry_run, **kwargs)
    else:
        sync_mcp_to_file(harness_root, config, dry_run, **kwargs)
