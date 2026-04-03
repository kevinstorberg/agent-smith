from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from scripts.shared.validation import MAX_TITLE_LENGTH, MAX_BODY_LENGTH

from services.api.models.plan import list_plans, search_plans, get_plan, create_plan, update_plan, delete_plan
from services.api.routers.base import require_found, list_response, delete_response, empty_to_none

router = APIRouter()


@router.get("")
def list_all(
    project: str = Query(""),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    items, total = list_plans(project=empty_to_none(project), limit=limit, offset=offset)
    return list_response(items, total)


@router.get("/search")
def search(q: str = Query(..., min_length=1), project: str = Query("")):
    return search_plans(q, project=empty_to_none(project))


@router.get("/{plan_id}")
def get_one(plan_id: int):
    return require_found(get_plan(plan_id), "Plan", plan_id)


class CreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    body: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)
    project: str | None = None


@router.post("", status_code=201)
def create(body: CreateRequest):
    plan_id = create_plan(body.title, body.body, project=body.project)
    return get_plan(plan_id)


class UpdateRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=MAX_TITLE_LENGTH)
    body: str | None = Field(None, min_length=1, max_length=MAX_BODY_LENGTH)
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
    return delete_response(plan_id)
