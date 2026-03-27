from __future__ import annotations

from psycopg2.extras import RealDictCursor

from services.db import get_connection


def _serialize(row: dict) -> dict:
    result = dict(row)
    if result.get("created_at"):
        result["created_at"] = result["created_at"].isoformat()
    if result.get("updated_at"):
        result["updated_at"] = result["updated_at"].isoformat()
    return result


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
            items = [_serialize(r) for r in cur.fetchall()]

    return items, total


def search_plans(query: str, project: str | None = None, limit: int = 10) -> list[dict]:
    assert query, "Search query must not be empty."
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
            return [_serialize(r) for r in cur.fetchall()]


def get_plan(plan_id: int) -> dict | None:
    assert plan_id > 0, "plan_id must be positive."
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM plans WHERE id = %s", (plan_id,))
            row = cur.fetchone()
            return _serialize(row) if row else None


def create_plan(title: str, body: str, project: str | None = None) -> int:
    assert title, "Title must not be empty."
    assert body, "Body must not be empty."
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
    assert plan_id > 0, "plan_id must be positive."
    sets = []
    params: list = []

    if title is not None:
        sets.append("title = %s")
        params.append(title)
    if body is not None:
        sets.append("body = %s")
        params.append(body)
    if project != "UNSET":
        sets.append("project = %s")
        params.append(project or None)

    assert sets, "At least one field must be provided."
    sets.append("updated_at = now()")
    params.append(plan_id)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE plans SET {', '.join(sets)} WHERE id = %s", params)


def delete_plan(plan_id: int) -> None:
    assert plan_id > 0, "plan_id must be positive."
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM plans WHERE id = %s", (plan_id,))
