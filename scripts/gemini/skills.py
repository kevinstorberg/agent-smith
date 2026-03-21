"""Sync skills to Gemini: copy skill directories -> ~/.gemini/skills/."""

from __future__ import annotations
from pathlib import Path
from scripts.shared.fs import sync_skills_from_config


def main(harness_root: Path, config: dict, dry_run: bool) -> None:
    sync_skills_from_config(harness_root, config, dry_run)
