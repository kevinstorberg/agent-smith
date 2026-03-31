from __future__ import annotations

import shutil
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

    path.write_text(content, encoding="utf-8")
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


def _compose_agent_file(body: str, metadata: dict, scoped_rules: list | None = None) -> str:
    parts = []
    if metadata:
        import yaml
        frontmatter = yaml.dump(metadata, default_flow_style=False).rstrip()
        parts.append(f"---\n{frontmatter}\n---\n")
    parts.append(body.rstrip())
    if scoped_rules:
        parts.append("\n\n# Rules\n")
        for rule in scoped_rules:
            parts.append(rule["content"]["body"].rstrip())
    return "\n\n".join(parts) + "\n"


def sync_agents(agent: str, dry_run: bool) -> None:
    from scripts.shared.agents import AGENT_TARGETS
    from services.db.harness import collect_agents_from_db

    cfg = AGENT_TARGETS[agent]
    agents_dir = cfg.get("agents_dir")
    if not agents_dir:
        return

    dest_dir = Path(agents_dir).expanduser()
    agent_defs = collect_agents_from_db(agent)

    if dry_run:
        print(f"  would sync {len(agent_defs)} agent(s) -> {dest_dir}")
        return

    dest_dir.mkdir(parents=True, exist_ok=True)
    source_names = set()

    for name, data in sorted(agent_defs.items()):
        filename = f"{name}.md"
        source_names.add(filename)
        content = _compose_agent_file(
            data["body"], data["metadata"], data.get("scoped_rules"),
        )
        _, msg = atomic_write(dest_dir / filename, content)
        print(f"  {msg}")

    for stale in dest_dir.glob("*.md"):
        if stale.name not in source_names:
            stale.unlink()
            print(f"  removed:   {stale}")
