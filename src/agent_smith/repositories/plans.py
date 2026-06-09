from sqlalchemy import func, or_, select

from db.models.agent_smith import Plan
from db.repository import BaseRepository


class PlanRepository(BaseRepository[Plan]):
    model = Plan

    async def list_page(self, *, project: str | None, limit: int, offset: int) -> tuple[list[Plan], int]:
        statement = select(Plan)
        count_statement = select(func.count()).select_from(Plan)
        if project:
            statement = statement.where(Plan.project == project)
            count_statement = count_statement.where(Plan.project == project)
        statement = statement.order_by(Plan.updated_at.desc()).limit(limit).offset(offset)

        rows = await self.session.execute(statement)
        total = await self.session.scalar(count_statement)
        return list(rows.scalars().all()), int(total or 0)

    async def search(self, query: str) -> list[Plan]:
        pattern = f"%{query}%"
        rows = await self.session.execute(
            select(Plan)
            .where(or_(Plan.title.ilike(pattern), Plan.body.ilike(pattern)))
            .order_by(Plan.updated_at.desc())
            .limit(50)
        )
        return list(rows.scalars().all())
