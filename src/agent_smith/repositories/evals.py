from __future__ import annotations

from sqlalchemy import delete, func, select

from db.models.agent_smith import EvalResult, EvalScenario, EvalSuite
from db.repository import BaseRepository
from src.agent_smith.serialization import model_to_dict, serialize_value


class EvalSuiteRepository(BaseRepository[EvalSuite]):
    model = EvalSuite

    async def list_page(self, *, enabled_only: bool, limit: int, offset: int) -> tuple[list[dict], int]:
        where = [EvalSuite.enabled.is_(True)] if enabled_only else []
        total_result = await self.session.execute(select(func.count()).select_from(EvalSuite).where(*where))
        rows_result = await self.session.execute(
            select(EvalSuite).where(*where).order_by(EvalSuite.name).limit(limit).offset(offset)
        )
        items = []
        for suite in rows_result.scalars().all():
            count_result = await self.session.execute(
                select(func.count()).select_from(EvalScenario).where(EvalScenario.suite_id == suite.id)
            )
            row = model_to_dict(
                suite,
                fields=("id", "name", "eval_type", "subcategory", "enabled", "created_at", "updated_at"),
            )
            row["scenario_count"] = int(count_result.scalar_one())
            items.append(row)
        return items, int(total_result.scalar_one())

    async def get_by_name(self, name: str) -> EvalSuite | None:
        result = await self.session.execute(select(EvalSuite).where(EvalSuite.name == name))
        return result.scalars().first()

    async def get_with_scenarios(self, suite_id: int) -> dict | None:
        suite = await self.get(suite_id)
        if suite is None:
            return None
        row = model_to_dict(suite)
        row["scenarios"] = await EvalScenarioRepository(self.session).list_for_suite(suite_id, enabled_only=False)
        return row


class EvalScenarioRepository(BaseRepository[EvalScenario]):
    model = EvalScenario

    async def list_for_suite(self, suite_id: int, *, enabled_only: bool = True) -> list[dict]:
        statement = select(EvalScenario).where(EvalScenario.suite_id == suite_id)
        if enabled_only:
            statement = statement.where(EvalScenario.enabled.is_(True))
        statement = statement.order_by(EvalScenario.sort_key, EvalScenario.name)
        result = await self.session.execute(statement)
        return [model_to_dict(row) for row in result.scalars().all()]

    async def get_by_suite_and_name(self, suite_id: int, name: str) -> EvalScenario | None:
        result = await self.session.execute(
            select(EvalScenario).where(EvalScenario.suite_id == suite_id, EvalScenario.name == name)
        )
        return result.scalars().first()


class EvalResultRepository(BaseRepository[EvalResult]):
    model = EvalResult

    async def list_page(self, *, filters: dict, limit: int, offset: int) -> tuple[list[dict], int]:
        where = self._where(filters)
        total_result = await self.session.execute(select(func.count()).select_from(EvalResult).where(*where))
        result = await self.session.execute(
            select(EvalResult).where(*where).order_by(EvalResult.timestamp.desc()).limit(limit).offset(offset)
        )
        items = []
        for row in result.scalars().all():
            item = model_to_dict(
                row,
                fields=(
                    "id",
                    "timestamp",
                    "eval_type",
                    "subcategory",
                    "scenario",
                    "test_model",
                    "judge_model",
                    "threshold",
                    "eval_suite_id",
                    "created_at",
                    "results",
                ),
            )
            scores = [float(result_item.get("score", 0)) for result_item in item.pop("results", [])]
            item["score_avg"] = round(sum(scores) / max(len(scores), 1), 3) if scores else 0
            item["score_count"] = len(scores)
            items.append(item)
        return items, int(total_result.scalar_one())

    async def categories(self) -> list[str]:
        result = await self.session.execute(select(EvalResult.eval_type).distinct().order_by(EvalResult.eval_type))
        return [row[0] for row in result.all()]

    async def subcategories(self, eval_type: str | None = None) -> list[str]:
        statement = select(EvalResult.subcategory).where(EvalResult.subcategory.is_not(None)).distinct()
        if eval_type:
            statement = statement.where(EvalResult.eval_type == eval_type)
        result = await self.session.execute(statement.order_by(EvalResult.subcategory))
        return [row[0] for row in result.all()]

    async def chart_rows(self, filters: dict) -> list[dict]:
        result = await self.session.execute(
            select(EvalResult).where(*self._where(filters)).order_by(EvalResult.timestamp.asc())
        )
        return [
            {"id": row.id, "timestamp": serialize_value(row.timestamp), "results": row.results}
            for row in result.scalars().all()
        ]

    async def delete_by_id(self, eval_id: int) -> bool:
        result = await self.session.execute(delete(EvalResult).where(EvalResult.id == eval_id).returning(EvalResult.id))
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _where(filters: dict) -> list:
        where = []
        for attr_name in ("scenario", "eval_type", "subcategory"):
            if value := filters.get(attr_name):
                where.append(getattr(EvalResult, attr_name) == value)
        if model := filters.get("model"):
            where.append(EvalResult.test_model == model)
        if date_from := filters.get("date_from"):
            where.append(EvalResult.timestamp >= date_from)
        if date_to := filters.get("date_to"):
            where.append(EvalResult.timestamp <= date_to)
        return where
