from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from services.db.plans import list_plans, search_plans, get_plan, create_plan, update_plan, delete_plan
from services.dashboard.routers.base import require_found

router = APIRouter()


@router.get("")
def list_all(
    project: str = Query(""),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    items, total = list_plans(project=project or None, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/search")
def search(q: str = Query(..., min_length=1), project: str = Query("")):
    return search_plans(q, project=project or None)


@router.get("/{plan_id}")
def get_one(plan_id: int):
    return require_found(get_plan(plan_id), "Plan", plan_id)


class CreateRequest(BaseModel):
    title: str
    body: str
    project: str | None = None


@router.post("", status_code=201)
def create(body: CreateRequest):
    plan_id = create_plan(body.title, body.body, project=body.project)
    return get_plan(plan_id)


class UpdateRequest(BaseModel):
    title: str | None = None
    body: str | None = None
    project: str | None = "UNSET"


@router.put("/{plan_id}")
def update(plan_id: int, body: UpdateRequest):
    update_plan(
        plan_id,
        title=body.title,
        body=body.body,
        project=body.project if body.project != "UNSET" else "UNSET",
    )
    return require_found(get_plan(plan_id), "Plan", plan_id)


@router.delete("/{plan_id}")
def delete(plan_id: int):
    require_found(get_plan(plan_id), "Plan", plan_id)
    delete_plan(plan_id)
    return {"deleted": True, "id": plan_id}
