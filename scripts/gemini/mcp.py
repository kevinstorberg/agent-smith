"""Sync MCP servers to Gemini: merge mcpServers key into ~/.gemini/settings.json."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.shared.fs import atomic_write
from scripts.shared.mcp_utils import sync_mcp_to_file


def _transform(srv: dict) -> dict:
    entry = {"httpUrl": srv["url"]}
    if "headers" in srv:
        entry["headers"] = srv["headers"]
    return entry


def main(harness_root: Path, config: dict, dry_run: bool) -> None:
    sync_mcp_to_file(
        harness_root, config, dry_run,
        read_file=lambda p: json.loads(p.read_text(encoding="utf-8")),
        write_file=lambda p, d: atomic_write(p, json.dumps(d, indent=2) + "\n"),
        transform_entry=_transform,
        dest_key="mcpServers",
    )
