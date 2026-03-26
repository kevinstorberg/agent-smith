from __future__ import annotations
from pathlib import Path
from scripts.shared.fs import sync_skills


def main(harness_root: Path, config: dict, dry_run: bool, source: str = "filesystem", agent: str = "claude", **_) -> None:
    sync_skills(harness_root, config, dry_run, source, agent)
