from __future__ import annotations
from pathlib import Path
from scripts.shared.fs import compose_rules_to_file


def main(harness_root: Path, config: dict, dry_run: bool) -> None:
    compose_rules_to_file(harness_root, config, dry_run)
