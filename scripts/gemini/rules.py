"""Sync rules to Gemini: compose harness/main.md + rules/shared/ into ~/.gemini/GEMINI.md."""

from __future__ import annotations

from pathlib import Path

from scripts.shared.fs import atomic_write, collect_md_files


def main(harness_root: Path, config: dict, dry_run: bool) -> None:
    for target in config.get("targets", []):
        dest = Path(target["path"]).expanduser()
        sources = target.get("compose", [])
        files = collect_md_files(sources, harness_root)
        content = "\n\n".join(f.read_text(encoding="utf-8").rstrip() for f in files) + "\n"
        if dry_run:
            print(f"  would compose {len(files)} file(s) → {dest}")
            continue
        _, msg = atomic_write(dest, content)
        print(f"  {msg}")
