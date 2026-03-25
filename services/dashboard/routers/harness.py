from __future__ import annotations

from fastapi import APIRouter, Query

from services.db.harness import list_rules, list_skills, list_tools, list_hooks

router = APIRouter()


@router.get("/rules")
def get_rules(project: str = Query(""), agent: str = Query("")):
    rows = list_rules(project=project or None, agent=agent or None)
    return [{"name": r["name"], "content": r["content"]["body"]} for r in rows]


@router.get("/skills")
def get_skills(project: str = Query(""), agent: str = Query("")):
    rows = list_skills(project=project or None, agent=agent or None)
    result = []
    for r in rows:
        meta = r["content"].get("metadata", {})
        files = sorted(meta.get("files", {}).keys())
        result.append({"name": r["name"], "content": r["content"]["body"], "files": files})
    return result


@router.get("/mcp")
def get_mcp(project: str = Query(""), agent: str = Query("")):
    rows = list_tools(project=project or None, agent=agent or None)
    return [{"name": r["name"], "config": r["content"].get("metadata", {})} for r in rows]


@router.get("/hooks")
def get_hooks(project: str = Query(""), agent: str = Query("")):
    rows = list_hooks(project=project or None, agent=agent or None)
    return [{"name": r["name"], "config": r["content"].get("metadata", {})} for r in rows]
