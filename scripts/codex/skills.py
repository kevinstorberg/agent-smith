"""Sync skills to Codex: copy skill directories → ~/.codex/skills/."""

from __future__ import annotations

from pathlib import Path

from scripts.shared.fs import collect_skill_dirs, sync_skill_dirs


def main(harness_root: Path, config: dict, dry_run: bool) -> None:
    for target in config.get("targets", []):
        dest_dir = Path(target["path"]).expanduser()
        sources = target.get("copy", [])
        skills = collect_skill_dirs(sources, harness_root)
        sync_skill_dirs(skills, dest_dir, dry_run)
