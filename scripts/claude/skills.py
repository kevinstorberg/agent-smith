from __future__ import annotations
from pathlib import Path
from scripts.shared.fs import sync_skills_from_config, sync_skills_from_db


def main(harness_root: Path, config: dict, dry_run: bool, source: str = "filesystem", agent: str = "claude", **_) -> None:
    if source == "db":
        sync_skills_from_db(agent, config, dry_run)
    else:
        sync_skills_from_config(harness_root, config, dry_run)
