from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.db.evals import (
    list_suites, get_suite, create_suite, update_suite, delete_suite,
    list_scenarios, get_scenario, create_scenario, update_scenario, delete_scenario,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateSuiteRequest(BaseModel):
    name: str
    eval_type: str
    subcategory: str
    judge_prompt: str
    items: dict = {}
    config: dict = {}
    enabled: bool = True


class UpdateSuiteRequest(BaseModel):
    name: str | None = None
    eval_type: str | None = None
    subcategory: str | None = None
    judge_prompt: str | None = None
    items: dict | None = None
    config: dict | None = None
    enabled: bool | None = None


class CreateScenarioRequest(BaseModel):
    name: str
    prompt: str
    enabled: bool = True


class UpdateScenarioRequest(BaseModel):
    name: str | None = None
    prompt: str | None = None
    enabled: bool | None = None


# ---------------------------------------------------------------------------
# Suite endpoints
# ---------------------------------------------------------------------------


@router.get("/suites")
def list_suites_endpoint(
    enabled_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    items, total = list_suites(enabled_only=enabled_only, limit=limit, offset=offset)
    for item in items:
        item["scenario_count"] = len(list_scenarios(item["id"], enabled_only=False))
    return {"items": items, "total": total}


@router.get("/suites/{suite_id}")
def get_suite_endpoint(suite_id: int):
    suite = get_suite(suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    suite["scenarios"] = list_scenarios(suite_id, enabled_only=False)
    return suite


@router.post("/suites", status_code=201)
def create_suite_endpoint(body: CreateSuiteRequest):
    suite_id = create_suite(
        name=body.name,
        eval_type=body.eval_type,
        subcategory=body.subcategory,
        judge_prompt=body.judge_prompt,
        items=body.items,
        config=body.config,
        enabled=body.enabled,
    )
    return get_suite(suite_id)


@router.put("/suites/{suite_id}")
def update_suite_endpoint(suite_id: int, body: UpdateSuiteRequest):
    if not get_suite(suite_id):
        raise HTTPException(status_code=404, detail="Suite not found")

    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    if kwargs:
        update_suite(suite_id, **kwargs)
    return get_suite(suite_id)


@router.delete("/suites/{suite_id}")
def delete_suite_endpoint(suite_id: int):
    if not get_suite(suite_id):
        raise HTTPException(status_code=404, detail="Suite not found")
    delete_suite(suite_id)
    return {"deleted": suite_id}


# ---------------------------------------------------------------------------
# Scenario endpoints
# ---------------------------------------------------------------------------


@router.get("/suites/{suite_id}/scenarios")
def list_scenarios_endpoint(suite_id: int, enabled_only: bool = Query(False)):
    if not get_suite(suite_id):
        raise HTTPException(status_code=404, detail="Suite not found")
    return list_scenarios(suite_id, enabled_only=enabled_only)


@router.get("/scenarios/{scenario_id}")
def get_scenario_endpoint(scenario_id: int):
    sc = get_scenario(scenario_id)
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return sc


@router.post("/suites/{suite_id}/scenarios", status_code=201)
def create_scenario_endpoint(suite_id: int, body: CreateScenarioRequest):
    if not get_suite(suite_id):
        raise HTTPException(status_code=404, detail="Suite not found")
    scenario_id = create_scenario(
        suite_id=suite_id,
        name=body.name,
        prompt=body.prompt,
        enabled=body.enabled,
    )
    return get_scenario(scenario_id)


@router.put("/scenarios/{scenario_id}")
def update_scenario_endpoint(scenario_id: int, body: UpdateScenarioRequest):
    if not get_scenario(scenario_id):
        raise HTTPException(status_code=404, detail="Scenario not found")

    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    if kwargs:
        update_scenario(scenario_id, **kwargs)
    return get_scenario(scenario_id)


@router.delete("/scenarios/{scenario_id}")
def delete_scenario_endpoint(scenario_id: int):
    if not get_scenario(scenario_id):
        raise HTTPException(status_code=404, detail="Scenario not found")
    delete_scenario(scenario_id)
    return {"deleted": scenario_id}
