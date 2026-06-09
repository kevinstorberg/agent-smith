from __future__ import annotations

from datetime import datetime

from db.models.agent_smith import EvalResult, EvalScenario, EvalSuite
from db.unit_of_work import UnitOfWork
from src.agent_smith.repositories.evals import EvalResultRepository, EvalScenarioRepository, EvalSuiteRepository
from src.agent_smith.serialization import model_to_dict
from src.agent_smith.services.harness import HarnessService
from src.services.application import ApplicationService


class EvalService(ApplicationService):
    async def list_results(self, uow: UnitOfWork, *, filters: dict, limit: int, offset: int):
        return await EvalResultRepository(uow.session).list_page(filters=filters, limit=limit, offset=offset)

    async def categories(self, uow: UnitOfWork) -> list[str]:
        return await EvalResultRepository(uow.session).categories()

    async def subcategories(self, uow: UnitOfWork, eval_type: str | None = None) -> list[str]:
        return await EvalResultRepository(uow.session).subcategories(eval_type=eval_type)

    async def chart(self, uow: UnitOfWork, *, filters: dict) -> list[dict]:
        rows = await EvalResultRepository(uow.session).chart_rows(filters)
        return [
            {"id": row["id"], "timestamp": row["timestamp"], "scores": {r["rule"]: r["score"] for r in row["results"]}}
            for row in rows
        ]

    async def chart_average(self, uow: UnitOfWork, *, filters: dict) -> list[dict]:
        rows = await EvalResultRepository(uow.session).chart_rows(filters)
        return [
            {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "score": sum(r["score"] for r in row["results"]) / max(len(row["results"]), 1),
            }
            for row in rows
        ]

    async def get_result(self, uow: UnitOfWork, eval_id: int) -> dict | None:
        row = await EvalResultRepository(uow.session).get(eval_id)
        return model_to_dict(row) if row else None

    async def delete_result(self, uow: UnitOfWork, eval_id: int) -> bool:
        return await EvalResultRepository(uow.session).delete_by_id(eval_id)

    async def save_result(
        self,
        uow: UnitOfWork,
        *,
        timestamp: datetime,
        eval_type: str,
        scenario: str,
        test_model: str,
        judge_model: str,
        threshold: float,
        output,
        results,
        subcategory: str | None = None,
        prompt: str | None = None,
        eval_suite_id: int | None = None,
        eval_scenario_id: int | None = None,
    ) -> int:
        result = EvalResult(
            timestamp=timestamp,
            eval_type=eval_type,
            subcategory=subcategory,
            scenario=scenario,
            test_model=test_model,
            judge_model=judge_model,
            threshold=threshold,
            prompt=prompt,
            output=output,
            results=results,
            eval_suite_id=eval_suite_id,
            eval_scenario_id=eval_scenario_id,
        )
        EvalResultRepository(uow.session).add(result)
        await uow.session.flush()
        return result.id

    async def list_suites(self, uow: UnitOfWork, *, enabled_only: bool, limit: int, offset: int):
        return await EvalSuiteRepository(uow.session).list_page(enabled_only=enabled_only, limit=limit, offset=offset)

    async def get_suite(self, uow: UnitOfWork, suite_id: int, *, include_scenarios: bool = False) -> dict | None:
        repo = EvalSuiteRepository(uow.session)
        if include_scenarios:
            return await repo.get_with_scenarios(suite_id)
        suite = await repo.get(suite_id)
        return model_to_dict(suite) if suite else None

    async def create_suite(self, uow: UnitOfWork, **fields) -> dict:
        suite = EvalSuite(**fields)
        EvalSuiteRepository(uow.session).add(suite)
        await uow.session.flush()
        return model_to_dict(suite)

    async def update_suite(self, uow: UnitOfWork, suite_id: int, **fields) -> dict | None:
        suite = await EvalSuiteRepository(uow.session).get(suite_id)
        if suite is None:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(suite, key, value)
        return model_to_dict(suite)

    async def delete_suite(self, uow: UnitOfWork, suite_id: int) -> bool:
        suite = await EvalSuiteRepository(uow.session).get(suite_id)
        if suite is None:
            return False
        await EvalSuiteRepository(uow.session).delete(suite)
        return True

    async def list_scenarios(self, uow: UnitOfWork, suite_id: int, *, enabled_only: bool) -> list[dict]:
        return await EvalScenarioRepository(uow.session).list_for_suite(suite_id, enabled_only=enabled_only)

    async def get_scenario(self, uow: UnitOfWork, scenario_id: int) -> dict | None:
        scenario = await EvalScenarioRepository(uow.session).get(scenario_id)
        return model_to_dict(scenario) if scenario else None

    async def create_scenario(self, uow: UnitOfWork, suite_id: int, **fields) -> dict:
        scenario = EvalScenario(suite_id=suite_id, **fields)
        EvalScenarioRepository(uow.session).add(scenario)
        await uow.session.flush()
        return model_to_dict(scenario)

    async def update_scenario(self, uow: UnitOfWork, scenario_id: int, **fields) -> dict | None:
        scenario = await EvalScenarioRepository(uow.session).get(scenario_id)
        if scenario is None:
            return None
        for key, value in fields.items():
            if value is not None:
                setattr(scenario, key, value)
        return model_to_dict(scenario)

    async def delete_scenario(self, uow: UnitOfWork, scenario_id: int) -> bool:
        scenario = await EvalScenarioRepository(uow.session).get(scenario_id)
        if scenario is None:
            return False
        await EvalScenarioRepository(uow.session).delete(scenario)
        return True

    async def upsert_suite(self, uow: UnitOfWork, **fields) -> int:
        repo = EvalSuiteRepository(uow.session)
        existing = await repo.get_by_name(fields["name"])
        if existing:
            for key, value in fields.items():
                setattr(existing, key, value)
            return existing.id
        suite = EvalSuite(**fields)
        repo.add(suite)
        await uow.session.flush()
        return suite.id

    async def upsert_scenario(
        self, uow: UnitOfWork, suite_id: int, *, name: str, prompt: str, enabled: bool = True
    ) -> int:
        repo = EvalScenarioRepository(uow.session)
        existing = await repo.get_by_suite_and_name(suite_id, name)
        if existing:
            existing.prompt = prompt
            existing.enabled = enabled
            return existing.id
        scenario = EvalScenario(suite_id=suite_id, name=name, prompt=prompt, enabled=enabled)
        repo.add(scenario)
        await uow.session.flush()
        return scenario.id

    async def resolve_items(self, uow: UnitOfWork, items: dict) -> list[tuple[str, str]]:
        return await HarnessService().resolve_items(uow, items)

    async def resolve_extra_context(self, uow: UnitOfWork, items: dict) -> str | None:
        if items.get("source") != "skill":
            return None
        skill_name = items.get("skill_name")
        if not skill_name:
            raise ValueError("skill source requires 'skill_name'")
        skill = await HarnessService().get_item_by_name(uow, "skill", skill_name)
        if not skill:
            raise ValueError(f"Skill not found in harness DB: {skill_name}")
        return skill["content"]["body"]
