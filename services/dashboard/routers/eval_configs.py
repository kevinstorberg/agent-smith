from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from services.db.evals import (
    list_suites, get_suite, create_suite, update_suite, delete_suite,
    list_scenarios, get_scenario, create_scenario, update_scenario, delete_scenario,
)
from services.dashboard.routers.base import require_found

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
    suite = require_found(get_suite(suite_id), "Suite", suite_id)
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
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    if kwargs:
        update_suite(suite_id, **kwargs)
    return require_found(get_suite(suite_id), "Suite", suite_id)


@router.delete("/suites/{suite_id}")
def delete_suite_endpoint(suite_id: int):
    require_found(get_suite(suite_id), "Suite", suite_id)
    delete_suite(suite_id)
    return {"deleted": suite_id}


# ---------------------------------------------------------------------------
# Scenario endpoints
# ---------------------------------------------------------------------------


@router.get("/suites/{suite_id}/scenarios")
def list_scenarios_endpoint(suite_id: int, enabled_only: bool = Query(False)):
    require_found(get_suite(suite_id), "Suite", suite_id)
    return list_scenarios(suite_id, enabled_only=enabled_only)


@router.get("/scenarios/{scenario_id}")
def get_scenario_endpoint(scenario_id: int):
    return require_found(get_scenario(scenario_id), "Scenario", scenario_id)


@router.post("/suites/{suite_id}/scenarios", status_code=201)
def create_scenario_endpoint(suite_id: int, body: CreateScenarioRequest):
    require_found(get_suite(suite_id), "Suite", suite_id)
    scenario_id = create_scenario(
        suite_id=suite_id,
        name=body.name,
        prompt=body.prompt,
        enabled=body.enabled,
    )
    return get_scenario(scenario_id)


@router.put("/scenarios/{scenario_id}")
def update_scenario_endpoint(scenario_id: int, body: UpdateScenarioRequest):
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    if kwargs:
        update_scenario(scenario_id, **kwargs)
    return require_found(get_scenario(scenario_id), "Scenario", scenario_id)


@router.delete("/scenarios/{scenario_id}")
def delete_scenario_endpoint(scenario_id: int):
    require_found(get_scenario(scenario_id), "Scenario", scenario_id)
    delete_scenario(scenario_id)
    return {"deleted": scenario_id}
