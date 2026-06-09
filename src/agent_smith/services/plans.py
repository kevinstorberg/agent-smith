from db.models.agent_smith import Plan
from db.unit_of_work import UnitOfWork
from src.agent_smith.repositories.plans import PlanRepository
from src.services.application import ApplicationService


class PlanService(ApplicationService):
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow
        self.repo = PlanRepository(uow.session)

    async def list_plans(self, *, project: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
        plans, total = await self.repo.list_page(project=project, limit=limit, offset=offset)
        return [_serialize_plan(plan) for plan in plans], total

    async def search_plans(self, query: str) -> list[dict]:
        return [_serialize_plan(plan) for plan in await self.repo.search(query)]

    async def get_plan(self, plan_id: int) -> dict | None:
        plan = await self.repo.get(plan_id)
        return _serialize_plan(plan) if plan else None

    async def create_plan(self, *, title: str, body: str, project: str | None) -> dict:
        plan = self.repo.add(Plan(title=title, body=body, project=project))
        await self.uow.session.flush()
        await self.repo.refresh(plan)
        return _serialize_plan(plan)

    async def update_plan(
        self,
        plan_id: int,
        *,
        title: str | None,
        body: str | None,
        project: str | None | object,
    ) -> dict | None:
        plan = await self.repo.get(plan_id)
        if plan is None:
            return None
        if title is not None:
            plan.title = title
        if body is not None:
            plan.body = body
        if project is not _UNSET:
            plan.project = project if isinstance(project, str) and project else None
        await self.uow.session.flush()
        await self.repo.refresh(plan)
        return _serialize_plan(plan)

    async def delete_plan(self, plan_id: int) -> bool:
        plan = await self.repo.get(plan_id)
        if plan is None:
            return False
        await self.repo.delete(plan)
        return True


_UNSET = object()


def unset_project() -> object:
    return _UNSET


def _serialize_plan(plan: Plan) -> dict:
    return {
        "id": plan.id,
        "title": plan.title,
        "body": plan.body,
        "project": plan.project,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }
