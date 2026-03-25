from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

FOOTER_MARKER = "<!-- footer -->"


def collect_md_files(sources: list[str], harness_root: Path) -> list[Path]:
    files: list[Path] = []
    for source in sources:
        path = (harness_root / source).expanduser().resolve()
        if path.is_file() and path.suffix == ".md":
            files.append(path)
        elif path.is_dir():
            files.extend(
                sorted(f for f in path.glob("*.md") if not f.name.startswith("."))
            )
    return files


def compose_parts(files: list[Path], transform=None) -> str:
    parts: list[str] = []
    footer_parts: list[str] = []
    for f in files:
        raw = f.read_text(encoding="utf-8").rstrip()
        if FOOTER_MARKER in raw:
            head, tail = raw.split(FOOTER_MARKER, 1)
            if head.strip():
                text = transform(head.rstrip(), f) if transform else head.rstrip()
                parts.append(text)
            if tail.strip():
                footer_parts.append(tail.strip())
        else:
            text = transform(raw, f) if transform else raw
            parts.append(text)
    return "\n\n".join(parts + footer_parts) + "\n"


def compose_strings(items: list[tuple[str, str]], transform=None) -> str:
    """Like compose_parts but accepts (name, content) tuples instead of file paths."""
    parts: list[str] = []
    footer_parts: list[str] = []
    for name, raw in items:
        raw = raw.rstrip()
        if FOOTER_MARKER in raw:
            head, tail = raw.split(FOOTER_MARKER, 1)
            if head.strip():
                text = transform(head.rstrip(), name) if transform else head.rstrip()
                parts.append(text)
            if tail.strip():
                footer_parts.append(tail.strip())
        else:
            text = transform(raw, name) if transform else raw
            parts.append(text)
    return "\n\n".join(parts + footer_parts) + "\n"


def extract_brief(content: str, rules_path: Path) -> str:
    """
    Return Rule + Action + a pointer line for a rule file.
    If no '* **Your Process:**' marker exists, returns content unchanged
    (handles files like execution_constraints.md that have no process loop).
    """
    marker = "* **Your Process:**"
    if marker not in content:
        return content
    before = content.split(marker)[0].rstrip()
    return f"{before}\n* **Your Process:** See `{rules_path}`\n"


def atomic_write(path: Path | str, content: str) -> tuple[bool, str]:
    """Write file atomically; skips write if content is unchanged."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False, f"unchanged: {path}"

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    os.replace(str(tmp_path), str(path))
    return True, f"updated:   {path}"


def collect_skill_dirs(sources: list[str], harness_root: Path) -> dict[str, Path]:
    skills: dict[str, Path] = {}
    for source in sources:
        path = (harness_root / source).expanduser().resolve()
        if path.is_dir():
            for candidate in sorted(path.iterdir()):
                if candidate.is_dir() and (candidate / "SKILL.md").is_file():
                    skills[candidate.name] = candidate
    return skills


def sync_skill_dirs(skills: dict[str, Path], dest_dir: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"  would sync {len(skills)} skill(s) → {dest_dir}")
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name, src_dir in skills.items():
        dest_skill = dest_dir / name
        dest_skill.mkdir(parents=True, exist_ok=True)
        src_files = {f.relative_to(src_dir) for f in src_dir.rglob("*") if f.is_file()}
        for rel in sorted(src_files):
            dest_file = dest_skill / rel
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            _, msg = atomic_write(dest_file, (src_dir / rel).read_text(encoding="utf-8"))
            print(f"  {msg}")
        for dest_file in list(dest_skill.rglob("*")):
            if dest_file.is_file() and dest_file.relative_to(dest_skill) not in src_files:
                dest_file.unlink()
                print(f"  removed:   {dest_file}")
    for stale in dest_dir.iterdir():
        if stale.is_dir() and stale.name not in skills:
            shutil.rmtree(stale)
            print(f"  removed:   {stale}")


def sync_skills_from_config(harness_root: Path, config: dict, dry_run: bool) -> None:
    for target in config.get("targets", []):
        dest_dir = Path(target["path"]).expanduser()
        skills = collect_skill_dirs(target.get("copy", []), harness_root)
        sync_skill_dirs(skills, dest_dir, dry_run)


def compose_rules_to_file(harness_root: Path, config: dict, dry_run: bool) -> None:
    for target in config.get("targets", []):
        path = Path(target["path"]).expanduser()
        if "compose" in target:
            files = collect_md_files(target["compose"], harness_root)
            content = compose_parts(files)
            if dry_run:
                print(f"  would compose {len(files)} file(s) -> {path}")
            else:
                _, msg = atomic_write(path, content)
                print(f"  {msg}")


def sync_skills_from_db(agent: str, config: dict, dry_run: bool, project: str | None = None) -> None:
    from services.db.harness import collect_skills_from_db
    skills = collect_skills_from_db(agent, project=project)
    for target in config.get("targets", []):
        dest_dir = Path(target["path"]).expanduser()
        if dry_run:
            print(f"  would sync {len(skills)} skill(s) → {dest_dir}")
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name, data in sorted(skills.items()):
            dest_skill = dest_dir / name
            dest_skill.mkdir(parents=True, exist_ok=True)
            _, msg = atomic_write(dest_skill / "SKILL.md", data["skill_md"])
            print(f"  {msg}")
            for rel_path, file_content in sorted(data.get("files", {}).items()):
                dest_file = dest_skill / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                _, msg = atomic_write(dest_file, file_content)
                print(f"  {msg}")
        for stale in dest_dir.iterdir():
            if stale.is_dir() and stale.name not in skills:
                shutil.rmtree(stale)
                print(f"  removed:   {stale}")
