from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from db.unit_of_work import UnitOfWork, get_unit_of_work
from src.agent_smith.responses import delete_response, list_response, require_found, update_fields
from src.agent_smith.services.evals import EvalService
from src.agent_smith.validation import MAX_BODY_LENGTH, MAX_NAME_LENGTH

evals_router = APIRouter()
eval_configs_router = APIRouter()
service = EvalService()


def _filters(**values) -> dict:
    return {key: value for key, value in values.items() if value}


@evals_router.get("")
async def list_evals(
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    scenario: str = Query(""),
    model: str = Query(""),
    eval_type: str = Query(""),
    subcategory: str = Query(""),
    date_from: str = Query(""),
    date_to: str = Query(""),
    limit: int = Query(10, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    items, total = await service.list_results(
        uow,
        filters=_filters(
            scenario=scenario,
            model=model,
            eval_type=eval_type,
            subcategory=subcategory,
            date_from=date_from,
            date_to=date_to,
        ),
        limit=limit,
        offset=offset,
    )
    return list_response(items, total)


@evals_router.get("/categories")
async def list_categories(uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    return await service.categories(uow)


@evals_router.get("/subcategories")
async def list_subcategories(uow: Annotated[UnitOfWork, Depends(get_unit_of_work)], eval_type: str = Query("")):
    return await service.subcategories(uow, eval_type=eval_type or None)


@evals_router.get("/chart")
async def chart_data(
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    scenario: str = Query(""),
    model: str = Query(""),
    eval_type: str = Query(""),
    subcategory: str = Query(""),
):
    return await service.chart(
        uow, filters=_filters(scenario=scenario, model=model, eval_type=eval_type, subcategory=subcategory)
    )


@evals_router.get("/chart/average")
async def chart_average(
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    scenario: str = Query(""),
    model: str = Query(""),
    eval_type: str = Query(""),
    subcategory: str = Query(""),
):
    return await service.chart_average(
        uow, filters=_filters(scenario=scenario, model=model, eval_type=eval_type, subcategory=subcategory)
    )


@evals_router.get("/{eval_id}")
async def get_eval(eval_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    return require_found(await service.get_result(uow, eval_id), "Eval", eval_id)


@evals_router.delete("/{eval_id}")
async def delete_eval(eval_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    deleted = await service.delete_result(uow, eval_id)
    require_found(deleted, "Eval", eval_id)
    return delete_response(eval_id)


class CreateSuiteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    eval_type: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    subcategory: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    judge_prompt: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)
    items: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class UpdateSuiteRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=MAX_NAME_LENGTH)
    eval_type: str | None = Field(None, min_length=1, max_length=MAX_NAME_LENGTH)
    subcategory: str | None = Field(None, min_length=1, max_length=MAX_NAME_LENGTH)
    judge_prompt: str | None = Field(None, min_length=1, max_length=MAX_BODY_LENGTH)
    items: dict | None = None
    config: dict | None = None
    enabled: bool | None = None


class CreateScenarioRequest(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    prompt: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)
    enabled: bool = True


class UpdateScenarioRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=MAX_NAME_LENGTH)
    prompt: str | None = Field(None, min_length=1, max_length=MAX_BODY_LENGTH)
    enabled: bool | None = None


@eval_configs_router.get("/suites")
async def list_suites_endpoint(
    uow: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    enabled_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    items, total = await service.list_suites(uow, enabled_only=enabled_only, limit=limit, offset=offset)
    return list_response(items, total)


@eval_configs_router.get("/suites/{suite_id}")
async def get_suite_endpoint(suite_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    return require_found(await service.get_suite(uow, suite_id, include_scenarios=True), "Suite", suite_id)


@eval_configs_router.post("/suites", status_code=201)
async def create_suite_endpoint(body: CreateSuiteRequest, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    return await service.create_suite(uow, **body.model_dump())


@eval_configs_router.put("/suites/{suite_id}")
async def update_suite_endpoint(
    suite_id: int, body: UpdateSuiteRequest, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]
):
    return require_found(await service.update_suite(uow, suite_id, **update_fields(body)), "Suite", suite_id)


@eval_configs_router.delete("/suites/{suite_id}")
async def delete_suite_endpoint(suite_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    deleted = await service.delete_suite(uow, suite_id)
    require_found(deleted, "Suite", suite_id)
    return delete_response(suite_id)


@eval_configs_router.get("/suites/{suite_id}/scenarios")
async def list_scenarios_endpoint(
    suite_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)], enabled_only: bool = Query(False)
):
    require_found(await service.get_suite(uow, suite_id), "Suite", suite_id)
    return await service.list_scenarios(uow, suite_id, enabled_only=enabled_only)


@eval_configs_router.get("/scenarios/{scenario_id}")
async def get_scenario_endpoint(scenario_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    return require_found(await service.get_scenario(uow, scenario_id), "Scenario", scenario_id)


@eval_configs_router.post("/suites/{suite_id}/scenarios", status_code=201)
async def create_scenario_endpoint(
    suite_id: int, body: CreateScenarioRequest, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]
):
    require_found(await service.get_suite(uow, suite_id), "Suite", suite_id)
    return await service.create_scenario(uow, suite_id, **body.model_dump())


@eval_configs_router.put("/scenarios/{scenario_id}")
async def update_scenario_endpoint(
    scenario_id: int, body: UpdateScenarioRequest, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]
):
    return require_found(
        await service.update_scenario(uow, scenario_id, **update_fields(body)), "Scenario", scenario_id
    )


@eval_configs_router.delete("/scenarios/{scenario_id}")
async def delete_scenario_endpoint(scenario_id: int, uow: Annotated[UnitOfWork, Depends(get_unit_of_work)]):
    deleted = await service.delete_scenario(uow, scenario_id)
    require_found(deleted, "Scenario", scenario_id)
    return delete_response(scenario_id)
