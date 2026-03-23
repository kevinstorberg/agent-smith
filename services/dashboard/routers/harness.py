from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from scripts.shared.fs import collect_md_files, collect_skill_dirs
from scripts.shared.mcp_utils import collect_mcp_servers

router = APIRouter()

REPO_ROOT = Path(__file__).parent.parent.parent.parent
HARNESS_ROOT = REPO_ROOT / "harness"
RULES_SOURCES = ["harness/rules/shared/"]
SKILLS_SOURCES = ["harness/skills/shared/"]
MCP_SOURCES = ["harness/mcp/shared/"]


@router.get("/rules")
def list_rules():
    files = collect_md_files(RULES_SOURCES, REPO_ROOT)
    return [
        {
            "name": f.stem,
            "content": f.read_text(encoding="utf-8"),
        }
        for f in files
    ]


@router.get("/skills")
def list_skills():
    skills = collect_skill_dirs(SKILLS_SOURCES, REPO_ROOT)
    result = []
    for name, path in sorted(skills.items()):
        skill_md = path / "SKILL.md"
        result.append({
            "name": name,
            "content": skill_md.read_text(encoding="utf-8") if skill_md.exists() else "",
            "files": sorted(str(f.relative_to(path)) for f in path.rglob("*") if f.is_file()),
        })
    return result


@router.get("/mcp")
def list_mcp():
    servers = collect_mcp_servers(MCP_SOURCES, REPO_ROOT)
    return [
        {"name": name, "config": config}
        for name, config in sorted(servers.items())
    ]
