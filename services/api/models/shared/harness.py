from __future__ import annotations

from psycopg2.extras import Json, RealDictCursor

from scripts.shared.validation import assert_not_empty
from services.db import get_connection
from services.api.models.base import BaseModel


def content_metadata(item: dict) -> dict:
    return item.get("content", {}).get("metadata", {})


VALID_TABLES = {
    "rule": "harness_rules",
    "skill": "harness_skills",
    "tool": "harness_tools",
    "hook": "harness_hooks",
    "agent": "harness_agents",
}

VALID_ITEM_TYPES = list(VALID_TABLES.keys())

_LATEST_VERSION_CLAUSE = """
    version = (
        SELECT MAX(v.version) FROM {table} v
        WHERE v.name = {table}.name
          AND v.project IS NOT DISTINCT FROM {table}.project
    )
"""


def _table(item_type: str) -> str:
    assert item_type in VALID_TABLES, f"Invalid type: {item_type}. Must be one of {set(VALID_TABLES)}."
    return VALID_TABLES[item_type]


def _sort_optional_list(value: list[str] | None) -> list[str] | None:
    return sorted(value) if value is not None else None


def _row_to_dict(row: dict) -> dict:
    result = dict(row)
    if result.get("agents") is not None:
        result["agents"] = sorted(result["agents"])
    if result.get("subagents") is not None:
        result["subagents"] = sorted(result["subagents"])
    return result


def _copy_configs(cursor, source_item_id: int, target_item_id: int, item_type: str) -> None:
    """Copy all harness_configs from source item to target item."""
    cursor.execute(
        """
        INSERT INTO harness_configs (item_id, item_type, device, repo, agents, subagents, enabled, exclude)
        SELECT %s, %s, device, repo, agents, subagents, enabled, exclude
        FROM harness_configs
        WHERE item_id = %s AND item_type = %s
        """,
        (target_item_id, item_type, source_item_id, item_type),
    )


def _get_model(item_type: str):
    from services.api.models.rule import RuleModel
    from services.api.models.skill import SkillModel
    from services.api.models.tool import ToolModel
    from services.api.models.hook import HookModel
    from services.api.models.agent import AgentModel
    registry = {
        "rule": RuleModel, "skill": SkillModel, "tool": ToolModel,
        "hook": HookModel, "agent": AgentModel,
    }
    return registry[item_type]


def _project_clause(project: str | None) -> tuple[str, list]:
    if project is None:
        return "AND project IS NULL", []
    return "AND project = %s", [project]


def _list_items_internal(
    item_type: str,
    project: str | None = None,
    agent: str | None = None,
    enabled_only: bool = True,
) -> list[dict]:
    table = _table(item_type)
    latest = _LATEST_VERSION_CLAUSE.format(table=table)

    query = f"SELECT * FROM {table}\n        WHERE {latest}\n          AND (project IS NULL OR project = %s)"
    params: list = [project]

    if enabled_only:
        query += "\n          AND enabled = true"

    if agent:
        query += "\n          AND %s = ANY(agents)"
        params.append(agent)

    query += "\n        ORDER BY sort_key"

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            rows = [_row_to_dict(r) for r in cur.fetchall()]

    if project is None:
        return rows

    seen = {}
    for row in rows:
        name = row["name"]
        if row["project"] is not None:
            seen[name] = row
        elif name not in seen:
            seen[name] = row

    return sorted(seen.values(), key=lambda r: r["sort_key"])


def list_items(item_type: str, project: str | None = None, agent: str | None = None) -> list[dict]:
    return _list_items_internal(item_type, project, agent, enabled_only=True)


def list_items_summary(item_type: str, project: str | None = None, agent: str | None = None) -> list[dict]:
    table = _table(item_type)
    latest = _LATEST_VERSION_CLAUSE.format(table=table)
    base_cols = "id, name, project, agents, sort_key, enabled, version, created_at, updated_at"
    cols = f"{base_cols}, clone_as_skill" if item_type == "rule" else base_cols

    query = f"SELECT {cols} FROM {table}\n        WHERE {latest}\n          AND (project IS NULL OR project = %s)"
    params: list = [project]

    if agent:
        query += "\n          AND %s = ANY(agents)"
        params.append(agent)

    query += "\n        ORDER BY sort_key"

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return [_row_to_dict(r) for r in cur.fetchall()]


def list_items_full(item_type: str, project: str | None = None, agent: str | None = None) -> list[dict]:
    return _list_items_internal(item_type, project, agent, enabled_only=False)


def get_item_by_id(item_type: str, item_id: int) -> dict | None:
    BaseModel._validate_id(item_id)
    table = _table(item_type)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {table} WHERE id = %s", (item_id,))
            row = cur.fetchone()
            if not row:
                return None
            result = _row_to_dict(row)
            cur.execute(
                "SELECT * FROM harness_configs WHERE item_id = %s AND item_type = %s ORDER BY id",
                (item_id, item_type),
            )
            result["configs"] = [_row_to_dict(r) for r in cur.fetchall()]
            return result


def create_item(
    item_type: str,
    name: str,
    content: dict,
    project: str | None = None,
    agents: list[str] | None = None,
    subagents: list[str] | None = None,
    sort_key: int | None = None,
    enabled: bool = True,
) -> int:
    assert_not_empty(name, "name")
    assert isinstance(content, dict) and "body" in content, "content must be a dict with a 'body' key."
    table = _table(item_type)

    agents = _sort_optional_list(agents)
    subagents = _sort_optional_list(subagents)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {table} (name, project, agents, subagents, content, sort_key, enabled, version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
                RETURNING id
                """,
                (name, project, agents or [], subagents or [], Json(content), sort_key if sort_key is not None else 0, enabled),
            )
            item_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO harness_configs (item_id, item_type, device, repo, agents, subagents, enabled, exclude)
                VALUES (%s, %s, '*', '*', %s, %s, %s, false)
                """,
                (item_id, item_type, agents or [], subagents or [], enabled),
            )
            return item_id


def update_content(item_type: str, item_id: int, content: dict) -> int:
    BaseModel._validate_id(item_id)
    assert isinstance(content, dict) and "body" in content, "content must be a dict with a 'body' key."
    table = _table(item_type)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {table} WHERE id = %s", (item_id,))
            source = cur.fetchone()
            assert source, f"Item not found: {item_id}"

            new_version = source["version"] + 1
            cur.execute(
                f"""
                INSERT INTO {table} (name, project, agents, subagents, content, sort_key, enabled, version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    source["name"], source["project"], source["agents"],
                    source["subagents"], Json(content), source["sort_key"],
                    source["enabled"], new_version,
                ),
            )
            new_id = cur.fetchone()["id"]
            _copy_configs(cur, item_id, new_id, item_type)
            return new_id


def update_metadata(
    item_type: str,
    item_id: int,
    enabled: bool | None = None,
    agents: list[str] | None = None,
    subagents: list[str] | None = None,
    name: str | None = None,
    sort_key: int | None = None,
    project: str | None = "UNSET",
    clone_as_skill: bool | None = None,
) -> None:
    _table(item_type)

    fields = BaseModel._collect_fields(
        enabled=enabled, name=name, sort_key=sort_key, clone_as_skill=clone_as_skill,
    )
    if agents is not None:
        fields["agents"] = _sort_optional_list(agents)
    if subagents is not None:
        fields["subagents"] = _sort_optional_list(subagents)
    if project != "UNSET":
        fields["project"] = project or None

    model = _get_model(item_type)
    model.dynamic_update(item_id, fields)


def reorder_items(item_type: str, ids: list[int]) -> None:
    assert_not_empty(ids, "ids")
    table = _table(item_type)

    with get_connection() as conn:
        with conn.cursor() as cur:
            for i, item_id in enumerate(ids):
                cur.execute(
                    f"UPDATE {table} SET sort_key = %s, updated_at = now() WHERE id = %s",
                    (i, item_id),
                )


def get_version_history(item_type: str, name: str, project: str | None = None) -> list[dict]:
    assert_not_empty(name, "name")
    table = _table(item_type)
    proj_clause, proj_params = _project_clause(project)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM {table} WHERE name = %s {proj_clause} ORDER BY version DESC",
                [name] + proj_params,
            )
            return [_row_to_dict(r) for r in cur.fetchall()]


def get_version_history_summary(item_type: str, name: str, project: str | None = None) -> list[dict]:
    assert_not_empty(name, "name")
    table = _table(item_type)
    proj_clause, proj_params = _project_clause(project)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT id, version, created_at FROM {table} WHERE name = %s {proj_clause} ORDER BY version DESC",
                [name] + proj_params,
            )
            return [dict(r) for r in cur.fetchall()]


def get_item(item_type: str, name: str, project: str | None = None) -> dict | None:
    assert_not_empty(name, "name")
    table = _table(item_type)
    latest = _LATEST_VERSION_CLAUSE.format(table=table)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if project:
                cur.execute(
                    f"SELECT * FROM {table} WHERE name = %s AND project = %s AND {latest}",
                    (name, project),
                )
                row = cur.fetchone()
                if row:
                    return _row_to_dict(row)

            cur.execute(
                f"SELECT * FROM {table} WHERE name = %s AND project IS NULL AND {latest}",
                (name,),
            )
            row = cur.fetchone()
            return _row_to_dict(row) if row else None


def upsert_item(
    item_type: str,
    name: str,
    content: dict,
    project: str | None = None,
    agents: list[str] | None = None,
    subagents: list[str] | None = None,
    sort_key: int | None = None,
    enabled: bool = True,
) -> int:
    assert_not_empty(name, "name")
    assert isinstance(content, dict) and "body" in content, "content must be a dict with a 'body' key."
    table = _table(item_type)

    agents = _sort_optional_list(agents)
    subagents = _sort_optional_list(subagents)

    existing = get_item(item_type, name, project=project)
    if existing:
        new_version = existing["version"] + 1
    else:
        new_version = 1

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {table} (name, project, agents, subagents, content, sort_key, enabled, version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (name, project, agents or [], subagents or [], Json(content), sort_key if sort_key is not None else 0, enabled, new_version),
            )
            item_id = cur.fetchone()[0]

            if new_version == 1:
                cur.execute(
                    """
                    INSERT INTO harness_configs (item_id, item_type, device, repo, agents, subagents, enabled, exclude)
                    VALUES (%s, %s, '*', '*', %s, %s, %s, false)
                    """,
                    (item_id, item_type, agents or [], subagents or [], enabled),
                )
            return item_id


def delete_item(item_type: str, item_id: int) -> None:
    table = _table(item_type)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM harness_configs WHERE item_id = %s AND item_type = %s",
                (item_id, item_type),
            )
            cur.execute(f"DELETE FROM {table} WHERE id = %s", (item_id,))
