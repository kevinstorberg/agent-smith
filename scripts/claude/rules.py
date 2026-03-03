"""
Sync rules to Claude:
  - compose targets: generate brief (Rule + Action + pointer) for each rule file
  - copy targets: mirror full rule files → destination directory; prune stale files
"""

from __future__ import annotations

from pathlib import Path

from scripts.shared.fs import atomic_write, collect_md_files, compose_parts, extract_brief


def main(harness_root: Path, config: dict, dry_run: bool) -> None:
    # Derive the rules/ directory from the sibling copy target so pointer URLs stay correct
    # Keep the tilde form for human-readable pointer URLs in CLAUDE.md
    rules_dir = next(
        (Path(t["path"]) for t in config.get("targets", []) if "copy" in t),
        None,
    )
    for target in config.get("targets", []):
        dest = Path(target["path"]).expanduser()
        if "compose" in target:
            _compose(harness_root, dest, target["compose"], rules_dir, dry_run)
        elif "copy" in target:
            _copy(harness_root, dest, target["copy"], dry_run)


def _compose(
    harness_root: Path,
    dest: Path,
    sources: list[str],
    rules_dir: Path | None,
    dry_run: bool,
) -> None:
    files = collect_md_files(sources, harness_root)
    content = compose_parts(
        files,
        transform=lambda text, f: extract_brief(text, rules_dir / f.name) if rules_dir else text,
    )
    if dry_run:
        print(f"  would compose {len(files)} file(s) → {dest}")
        return
    _, msg = atomic_write(dest, content)
    print(f"  {msg}")


def _copy(harness_root: Path, dest_dir: Path, sources: list[str], dry_run: bool) -> None:
    files = collect_md_files(sources, harness_root)
    if dry_run:
        print(f"  would copy {len(files)} file(s) → {dest_dir}")
        return

    dest_dir.mkdir(parents=True, exist_ok=True)
    source_names = {f.name for f in files}

    for src in files:
        _, msg = atomic_write(dest_dir / src.name, src.read_text(encoding="utf-8"))
        print(f"  {msg}")

    for stale in dest_dir.glob("*.md"):
        if stale.name not in source_names:
            stale.unlink()
            print(f"  removed:   {stale}")
