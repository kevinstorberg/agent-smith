from __future__ import annotations

from pathlib import Path

from scripts.shared.fs import (
    atomic_write, collect_md_files, compose_parts, compose_strings, extract_brief,
)


def main(harness_root: Path, config: dict, dry_run: bool, source: str = "filesystem", agent: str = "claude", **_) -> None:
    rules_dir = next(
        (Path(t["path"]) for t in config.get("targets", []) if "copy" in t),
        None,
    )
    for target in config.get("targets", []):
        dest = Path(target["path"]).expanduser()
        if "compose" in target:
            _compose(harness_root, dest, target["compose"], rules_dir, dry_run, source, agent)
        elif "copy" in target:
            _copy(harness_root, dest, target["copy"], dry_run, source, agent)


def _compose(
    harness_root: Path,
    dest: Path,
    sources: list[str],
    rules_dir: Path | None,
    dry_run: bool,
    source: str,
    agent: str,
) -> None:
    if source == "db":
        from services.db.harness import collect_rules_from_db
        items = collect_rules_from_db(agent)
        content = compose_strings(
            items,
            transform=lambda text, name: extract_brief(text, rules_dir / f"{name}.md") if rules_dir else text,
        )
        count = len(items)
    else:
        files = collect_md_files(sources, harness_root)
        content = compose_parts(
            files,
            transform=lambda text, f: extract_brief(text, rules_dir / f.name) if rules_dir else text,
        )
        count = len(files)

    if dry_run:
        print(f"  would compose {count} file(s) → {dest}")
        return
    _, msg = atomic_write(dest, content)
    print(f"  {msg}")


def _copy(harness_root: Path, dest_dir: Path, sources: list[str], dry_run: bool, source: str, agent: str) -> None:
    if source == "db":
        from services.db.harness import collect_rules_from_db
        items = collect_rules_from_db(agent)
        if dry_run:
            print(f"  would copy {len(items)} file(s) → {dest_dir}")
            return
        dest_dir.mkdir(parents=True, exist_ok=True)
        source_names = {f"{name}.md" for name, _ in items}
        for name, body in items:
            _, msg = atomic_write(dest_dir / f"{name}.md", body)
            print(f"  {msg}")
    else:
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
