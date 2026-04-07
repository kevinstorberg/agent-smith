from __future__ import annotations

from psycopg2.extras import Json, RealDictCursor

from services.db import get_connection


class VersioningMixin:
    @classmethod
    def update_content(cls, item_id: int, content: dict) -> int:
        cls._validate_id(item_id)
        assert isinstance(content, dict) and "body" in content, "content must be a dict with a 'body' key."

        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SELECT * FROM {cls.table} WHERE id = %s", (item_id,))
                source = cur.fetchone()
                assert source, f"Item not found: {item_id}"

                new_version = source["version"] + 1
                cur.execute(
                    f"""
                    INSERT INTO {cls.table} (name, project, agents, subagents, content, sort_key, enabled, version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        source["name"], source["project"], source["agents"],
                        source["subagents"], Json(content), source["sort_key"],
                        source["enabled"], new_version,
                    ),
                )
                return cur.fetchone()["id"]

    @classmethod
    def get_version_history(cls, name: str, project: str | None = None) -> list[dict]:
        from services.api.models.shared.harness import _project_clause, _row_to_dict
        from scripts.shared.validation import assert_not_empty
        assert_not_empty(name, "name")
        proj_clause, proj_params = _project_clause(project)

        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"SELECT * FROM {cls.table} WHERE name = %s {proj_clause} ORDER BY version DESC",
                    [name] + proj_params,
                )
                return [_row_to_dict(r) for r in cur.fetchall()]

    @classmethod
    def get_version_history_summary(cls, name: str, project: str | None = None) -> list[dict]:
        from services.api.models.shared.harness import _project_clause
        from scripts.shared.validation import assert_not_empty
        assert_not_empty(name, "name")
        proj_clause, proj_params = _project_clause(project)

        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"SELECT id, version, created_at FROM {cls.table} WHERE name = %s {proj_clause} ORDER BY version DESC",
                    [name] + proj_params,
                )
                return [dict(r) for r in cur.fetchall()]
