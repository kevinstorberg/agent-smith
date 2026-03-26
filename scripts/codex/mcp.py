from __future__ import annotations
from pathlib import Path
from scripts.shared.mcp_utils import sync_mcp


def main(harness_root: Path, config: dict, dry_run: bool, source: str = "filesystem", agent: str = "codex", **_) -> None:
    sync_mcp(harness_root, config, dry_run, source, agent)
