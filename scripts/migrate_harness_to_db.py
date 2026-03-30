#!/usr/bin/env -S .venv/bin/python3
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.shared.paths import bootstrap, REPO_ROOT  # noqa: E402
bootstrap()

from services.db import init_db  # noqa: E402
from services.db.harness import upsert_rule, upsert_skill, upsert_tool  # noqa: E402

from services.config import ALL_AGENTS  # noqa: E402

HARNESS_ROOT = REPO_ROOT / "harness"


def _parse_skill_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    end = text.index("---", 3)
    frontmatter = text[3:end].strip()
    description = ""
    for line in frontmatter.splitlines():
        if line.startswith("description:"):
            description = line.split(":", 1)[1].strip()
    return description, text


def _migrate_rules() -> int:
    count = 0

    # main.md lives at the harness root, not in rules/shared/
    main_path = HARNESS_ROOT / "main.md"
    if main_path.exists():
        upsert_rule(
            "main",
            content={"body": main_path.read_text(encoding="utf-8"), "metadata": {}},
            agents=ALL_AGENTS,
        )
        count += 1

    rules_dir = HARNESS_ROOT / "rules" / "shared"
    for f in sorted(rules_dir.glob("*.md")):
        upsert_rule(
            f.stem,
            content={"body": f.read_text(encoding="utf-8"), "metadata": {}},
            agents=ALL_AGENTS,
        )
        count += 1

    return count


def _migrate_skills() -> int:
    count = 0
    skills_dir = HARNESS_ROOT / "skills" / "shared"
    for skill_dir in sorted(d for d in skills_dir.iterdir() if d.is_dir()):
        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.exists():
            continue

        skill_md = skill_md_path.read_text(encoding="utf-8")
        description, _ = _parse_skill_frontmatter(skill_md)

        files = {}
        for file_path in sorted(skill_dir.rglob("*")):
            if file_path.is_file() and file_path.name != "SKILL.md":
                rel = str(file_path.relative_to(skill_dir))
                files[rel] = file_path.read_text(encoding="utf-8")

        upsert_skill(
            skill_dir.name,
            content={"body": skill_md, "metadata": {"description": description, "files": files}},
            agents=ALL_AGENTS,
        )
        count += 1

    return count


def _migrate_tools() -> int:
    count = 0
    mcp_dir = HARNESS_ROOT / "mcp" / "shared"
    for f in sorted(mcp_dir.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        name = data.pop("name", f.stem)
        upsert_tool(
            name,
            content={"body": "", "metadata": data},
            agents=ALL_AGENTS,
        )
        count += 1

    return count


def main() -> None:
    print("[1/4] Initializing database...")
    init_db()

    print("[2/4] Migrating rules...")
    rule_count = _migrate_rules()
    print(f"  {rule_count} rules")

    print("[3/4] Migrating skills...")
    skill_count = _migrate_skills()
    print(f"  {skill_count} skills")

    print("[4/4] Migrating tools...")
    tool_count = _migrate_tools()
    print(f"  {tool_count} tools")

    total = rule_count + skill_count + tool_count
    print(f"\nMigration complete: {total} items imported.")
    print("Filesystem files have NOT been deleted.")


if __name__ == "__main__":
    main()
