from __future__ import annotations
from pathlib import Path
from scripts.shared.fs import compose_rules_to_file, compose_strings, atomic_write


def main(harness_root: Path, config: dict, dry_run: bool, source: str = "filesystem", agent: str = "gemini", **_) -> None:
    if source == "db":
        from services.db.harness import collect_rules_from_db
        items = collect_rules_from_db(agent)
        content = compose_strings(items)
        for target in config.get("targets", []):
            path = Path(target["path"]).expanduser()
            if dry_run:
                print(f"  would compose {len(items)} file(s) -> {path}")
            else:
                _, msg = atomic_write(path, content)
                print(f"  {msg}")
    else:
        compose_rules_to_file(harness_root, config, dry_run)
