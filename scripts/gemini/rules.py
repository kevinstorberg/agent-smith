from __future__ import annotations
from pathlib import Path
from scripts.shared.fs import compose_rules_to_file, compose_rules_from_db


def main(harness_root: Path, config: dict, dry_run: bool, source: str = "filesystem", agent: str = "gemini", **_) -> None:
    if source == "db":
        compose_rules_from_db(agent, config, dry_run)
    else:
        compose_rules_to_file(harness_root, config, dry_run)
