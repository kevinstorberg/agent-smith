from __future__ import annotations

from psycopg2.extras import RealDictCursor

from scripts.shared.validation import assert_not_empty
from services.db import get_connection
from services.api.models.base import BaseModel


class PlanModel(BaseModel):
    table = "plans"

    @classmethod
    def create(cls, title: str, body: str, project: str | None = None) -> int:
        cls._validate_required({"title": title, "body": body}, ["title", "body"])
        return super().create(title=title, body=body, project=project)

    @classmethod
    def list(cls, project: str | None = None, limit: int = 10, offset: int = 0) -> tuple[list[dict], int]:
        where, params = ("WHERE project = %s", (project,)) if project else ("", ())
        return super().list(
            columns="id, title, project, created_at, updated_at",
            where=where, params=params, limit=limit, offset=offset,
        )

    @classmethod
    def update(cls, plan_id: int, title: str | None = None, body: str | None = None, project: str | None = "UNSET") -> None:
        fields = cls._collect_fields(title=title, body=body)
        if project != "UNSET":
            fields["project"] = project or None
        if fields:
            cls.dynamic_update(plan_id, fields)

    @classmethod
    def search(cls, query: str, project: str | None = None, limit: int = 100) -> list[dict]:
        assert_not_empty(query, "query")
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                sql = f"SELECT * FROM {cls.table} WHERE title ILIKE %s"
                params: list = [f"%{query}%"]
                if project:
                    sql += " AND project = %s"
                    params.append(project)
                sql += " ORDER BY updated_at DESC LIMIT %s"
                params.append(limit)
                cur.execute(sql, params)
                return [cls.serialize_timestamps(r) for r in cur.fetchall()]


list_plans = PlanModel.list
search_plans = PlanModel.search
get_plan = PlanModel.read
create_plan = PlanModel.create
update_plan = PlanModel.update
delete_plan = PlanModel.destroy
