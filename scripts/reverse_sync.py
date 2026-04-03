#!/usr/bin/env -S .venv/bin/python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.shared.paths import bootstrap  # noqa: E402
bootstrap()

from scripts.shared.agents import AGENT_TARGETS, _read_config  # noqa: E402
from services.config import ALL_AGENTS  # noqa: E402
from services.db import init_db  # noqa: E402
from services.api.models.shared.harness import upsert_item  # noqa: E402


def _slugify(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")


def _parse_skill_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return ""
    end = text.index("---", 3)
    for line in text[3:end].strip().splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip()
    return ""


def _reverse_mcp_transform(agent: str, server_config: dict) -> dict:
    meta: dict = {}
    if agent == "claude":
        meta["url"] = server_config.get("url", "")
        if "headers" in server_config:
            meta["headers"] = server_config["headers"]
        if "oauth" in server_config:
            meta["oauth"] = server_config["oauth"]
    elif agent == "codex":
        meta["url"] = server_config.get("url", "")
        if "headers" in server_config:
            meta["headers"] = server_config["headers"]
    elif agent == "gemini":
        meta["url"] = server_config.get("httpUrl", server_config.get("url", ""))
        if "headers" in server_config:
            meta["headers"] = server_config["headers"]
    return meta


def import_rules(agent: str, dry_run: bool) -> int:
    cfg = AGENT_TARGETS[agent]
    count = 0

    if "rules_dir" in cfg:
        rules_dir = Path(cfg["rules_dir"]).expanduser()
        if rules_dir.is_dir():
            for i, f in enumerate(sorted(rules_dir.glob("*.md"))):
                body = f.read_text(encoding="utf-8")
                if dry_run:
                    print(f"  [dry-run] rule: {f.stem}")
                else:
                    upsert_item("rule", f.stem, content={"body": body, "metadata": {}}, agents=ALL_AGENTS, sort_key=i)
                    print(f"  rule: {f.stem}")
                count += 1
            return count

    rules_file = Path(cfg["rules_file"]).expanduser()
    if not rules_file.exists():
        return 0

    text = rules_file.read_text(encoding="utf-8")
    sections = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    for i, section in enumerate(sections):
        section = section.strip()
        if not section:
            continue
        match = re.match(r"^## (.+)", section)
        name = _slugify(match.group(1)) if match else f"section_{i}"
        if dry_run:
            print(f"  [dry-run] rule: {name}")
        else:
            upsert_item("rule", name, content={"body": section, "metadata": {}}, agents=ALL_AGENTS, sort_key=i)
            print(f"  rule: {name}")
        count += 1

    return count


def import_skills(agent: str, dry_run: bool) -> int:
    cfg = AGENT_TARGETS[agent]
    skills_dir = Path(cfg["skills_dir"]).expanduser()
    if not skills_dir.is_dir():
        return 0

    count = 0
    for skill_dir in sorted(d for d in skills_dir.iterdir() if d.is_dir()):
        skill_md_path = skill_dir / "SKILL.md"
        if not skill_md_path.exists():
            continue

        skill_md = skill_md_path.read_text(encoding="utf-8")
        description = _parse_skill_frontmatter(skill_md)

        files = {}
        for file_path in sorted(skill_dir.rglob("*")):
            if file_path.is_file() and file_path.name != "SKILL.md":
                rel = str(file_path.relative_to(skill_dir))
                try:
                    files[rel] = file_path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    pass

        if dry_run:
            print(f"  [dry-run] skill: {skill_dir.name}")
        else:
            upsert_item(
                "skill", skill_dir.name,
                content={"body": skill_md, "metadata": {"description": description, "files": files}},
                agents=ALL_AGENTS,
            )
            print(f"  skill: {skill_dir.name}")
        count += 1

    return count


def import_tools(agent: str, dry_run: bool) -> int:
    cfg = AGENT_TARGETS[agent]
    mcp_file = Path(cfg["mcp_file"]).expanduser()
    if not mcp_file.exists():
        return 0

    data = _read_config(mcp_file, cfg["mcp_format"])
    servers = data.get(cfg["mcp_key"], {})

    count = 0
    for name, server_config in sorted(servers.items()):
        meta = _reverse_mcp_transform(agent, server_config)
        if dry_run:
            print(f"  [dry-run] tool: {name}")
        else:
            upsert_item("tool", name, content={"body": "", "metadata": meta}, agents=ALL_AGENTS)
            print(f"  tool: {name}")
        count += 1

    return count


def main() -> int:
    parser = argparse.ArgumentParser(prog="reverse_sync.py")
    parser.add_argument("--agent", choices=ALL_AGENTS, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run:
        init_db()

    agents = [args.agent] if args.agent else ALL_AGENTS

    for agent in agents:
        print(f"\n[{agent}/rules]")
        rule_count = import_rules(agent, args.dry_run)

        print(f"[{agent}/skills]")
        skill_count = import_skills(agent, args.dry_run)

        print(f"[{agent}/tools]")
        tool_count = import_tools(agent, args.dry_run)

        total = rule_count + skill_count + tool_count
        print(f"  {agent}: {rule_count} rules, {skill_count} skills, {tool_count} tools ({total} total)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
