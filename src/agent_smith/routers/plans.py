from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from db.unit_of_work import UnitOfWork, get_unit_of_work
from src.agent_smith.services.plans import PlanService, unset_project

router = APIRouter()


class PlanCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    project: str | None = None


class PlanUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1)
    project: str | None = None


@router.get("")
async def list_plans(
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    project: str = Query(""),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    items, total = await PlanService(uow).list_plans(project=project or None, limit=limit, offset=offset)
    return {"items": items, "total": total}


@router.get("/search")
async def search_plans(
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    q: str = Query(..., min_length=1),
):
    return await PlanService(uow).search_plans(q)


@router.get("/{plan_id}")
async def get_plan(plan_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    plan = await PlanService(uow).get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")
    return plan


@router.post("", status_code=201)
async def create_plan(body: PlanCreate, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    return await PlanService(uow).create_plan(title=body.title, body=body.body, project=body.project)


@router.put("/{plan_id}")
async def update_plan(
    plan_id: int,
    body: PlanUpdate,
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
):
    project = body.project if "project" in body.model_fields_set else unset_project()
    plan = await PlanService(uow).update_plan(plan_id, title=body.title, body=body.body, project=project)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")
    return plan


@router.delete("/{plan_id}")
async def delete_plan(plan_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    if not await PlanService(uow).delete_plan(plan_id):
        raise HTTPException(status_code=404, detail=f"Plan not found: {plan_id}")
    return {"deleted": True, "id": plan_id}
