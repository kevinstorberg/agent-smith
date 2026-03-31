from __future__ import annotations

from psycopg2.extras import RealDictCursor

from scripts.shared.validation import assert_not_empty
from services.db import get_connection
from services.db.base_model import BaseModel


class PlanModel(BaseModel):
    table = "plans"

    @classmethod
    def update(
        cls,
        plan_id: int,
        title: str | None = None,
        body: str | None = None,
        project: str | None = "UNSET",
    ) -> None:
        fields = {}
        if title is not None:
            fields["title"] = title
        if body is not None:
            fields["body"] = body
        if project != "UNSET":
            fields["project"] = project or None
        cls.dynamic_update(plan_id, fields)


def list_plans(
    project: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[dict], int]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if project:
                cur.execute("SELECT count(*) as cnt FROM plans WHERE project = %s", (project,))
            else:
                cur.execute("SELECT count(*) as cnt FROM plans")
            total = cur.fetchone()["cnt"]

            query = "SELECT * FROM plans"
            params: list = []
            if project:
                query += " WHERE project = %s"
                params.append(project)
            query += " ORDER BY updated_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cur.execute(query, params)
            items = [PlanModel.serialize_timestamps(r) for r in cur.fetchall()]

    return items, total


def search_plans(query: str, project: str | None = None, limit: int = 100) -> list[dict]:
    assert_not_empty(query, "query")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            sql = "SELECT * FROM plans WHERE title ILIKE %s"
            params: list = [f"%{query}%"]
            if project:
                sql += " AND project = %s"
                params.append(project)
            sql += " ORDER BY updated_at DESC LIMIT %s"
            params.append(limit)
            cur.execute(sql, params)
            return [PlanModel.serialize_timestamps(r) for r in cur.fetchall()]


def get_plan(plan_id: int) -> dict | None:
    return PlanModel.find_by_id(plan_id)


def create_plan(title: str, body: str, project: str | None = None) -> int:
    assert_not_empty(title, "title")
    assert_not_empty(body, "body")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO plans (title, body, project) VALUES (%s, %s, %s) RETURNING id",
                (title, body, project),
            )
            return cur.fetchone()[0]


def update_plan(
    plan_id: int,
    title: str | None = None,
    body: str | None = None,
    project: str | None = "UNSET",
) -> None:
    PlanModel.update(plan_id, title=title, body=body, project=project)


def delete_plan(plan_id: int) -> None:
    PlanModel.delete_by_id(plan_id)
