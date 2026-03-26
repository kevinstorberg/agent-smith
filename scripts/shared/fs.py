from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def compose_strings(items: list[tuple[str, str]], transform=None) -> str:
    parts: list[str] = []
    for name, raw in items:
        raw = raw.rstrip()
        text = transform(raw, name) if transform else raw
        parts.append(text)
    return "\n\n".join(parts) + "\n"


def extract_brief(content: str, rules_path: Path) -> str:
    marker = "* **Your Process:**"
    if marker not in content:
        return content
    before = content.split(marker)[0].rstrip()
    return f"{before}\n* **Your Process:** See `{rules_path}`\n"


def atomic_write(path: Path | str, content: str) -> tuple[bool, str]:
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


def sync_rules(agent: str, dry_run: bool) -> None:
    from scripts.shared.agents import AGENT_TARGETS
    from services.db.harness import collect_rules_from_db

    cfg = AGENT_TARGETS[agent]
    items = collect_rules_from_db(agent)
    rules_file = Path(cfg["rules_file"]).expanduser()
    rules_dir = Path(cfg["rules_dir"]).expanduser() if "rules_dir" in cfg else None

    if rules_dir:
        transform = lambda text, name: extract_brief(text, rules_dir / f"{name}.md")
    else:
        transform = None

    content = compose_strings(items, transform=transform)

    if dry_run:
        print(f"  would compose {len(items)} file(s) -> {rules_file}")
    else:
        _, msg = atomic_write(rules_file, content)
        print(f"  {msg}")

    if rules_dir:
        _sync_rules_dir(items, rules_dir, dry_run)


def _sync_rules_dir(items: list[tuple[str, str]], dest_dir: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"  would copy {len(items)} file(s) -> {dest_dir}")
        return

    dest_dir.mkdir(parents=True, exist_ok=True)
    source_names = {f"{name}.md" for name, _ in items}

    for name, body in items:
        _, msg = atomic_write(dest_dir / f"{name}.md", body)
        print(f"  {msg}")

    for stale in dest_dir.glob("*.md"):
        if stale.name not in source_names:
            stale.unlink()
            print(f"  removed:   {stale}")


def sync_skills(agent: str, dry_run: bool) -> None:
    from scripts.shared.agents import AGENT_TARGETS
    from services.db.harness import collect_skills_from_db

    skills = collect_skills_from_db(agent)
    dest_dir = Path(AGENT_TARGETS[agent]["skills_dir"]).expanduser()

    if dry_run:
        print(f"  would sync {len(skills)} skill(s) -> {dest_dir}")
        return

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
