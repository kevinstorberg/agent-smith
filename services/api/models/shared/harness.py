from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext

from psycopg2.errors import LockNotAvailable, QueryCanceled
from psycopg2.extensions import connection as Connection
from psycopg2.extras import Json, RealDictCursor

from scripts.shared.agents import VIRTUAL_AGENTS
from scripts.shared.validation import assert_not_empty
from services.db import get_connection
from services.api.models.base import BaseModel
from services.api.models.shared.listing import bidirectional_sorts, sort_clause

_CONFIG_COUNT_SORTS = bidirectional_sorts(
    {
        ("config_count_asc", "config_count_desc"): (
            "COALESCE(config_counts.config_count, 0)",
        )
    }
)
_RULE_CLONE_SORTS = bidirectional_sorts(
    {("clone_as_skill_asc", "clone_as_skill_desc"): ("clone_as_skill",)}
)
HARNESS_SORTS = {
    **bidirectional_sorts(
        {
            ("manual", "manual_desc"): ("sort_key",),
            ("name", "name_desc"): ("lower(name)",),
            ("project_asc", "project_desc"): ("NULLIF(lower(project), '')",),
            ("enabled_asc", "enabled_desc"): ("enabled",),
            ("agents_asc", "agents_desc"): (
                "NULLIF(ARRAY(SELECT lower(listed.agent) FROM unnest(agents) AS listed(agent) ORDER BY lower(listed.agent)), ARRAY[]::text[])",
            ),
            ("version_asc", "version_desc"): ("version",),
            ("updated_asc", "updated"): ("updated_at",),
        }
    ),
    **_CONFIG_COUNT_SORTS,
    **_RULE_CLONE_SORTS,
    "newest": "created_at DESC, id DESC",
}


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
    assert item_type in VALID_TABLES, (
        f"Invalid type: {item_type}. Must be one of {set(VALID_TABLES)}."
    )
    return VALID_TABLES[item_type]


class HarnessWriteConflict(RuntimeError):
    pass


@contextmanager
def harness_write(
    item_type: str, conn: Connection | None = None
) -> Iterator[Connection]:
    _table(item_type)
    try:
        with get_connection() if conn is None else nullcontext(conn) as connection:
            with connection.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '3s'")
                cur.execute("SET LOCAL statement_timeout = '5s'")
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"agent-smith:harness-write:{item_type}",),
                )
            yield connection
    except (LockNotAvailable, QueryCanceled):
        raise HarnessWriteConflict(
            "Harness items are busy. Refresh the list before trying again."
        ) from None


def _sort_optional_list(value: list[str] | None) -> list[str] | None:
    return sorted(value) if value is not None else None


def _row_to_dict(row: dict) -> dict:
    result = dict(row)
    if result.get("agents") is not None:
        result["agents"] = sorted(result["agents"])
    if result.get("subagents") is not None:
        result["subagents"] = sorted(result["subagents"])
    return result


def _copy_configs(
    cursor, source_item_id: int, target_item_id: int, item_type: str
) -> None:
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


def inherited_version_metadata(item_type: str, source: dict | None) -> dict[str, bool]:
    _table(item_type)
    if item_type != "rule" or source is None:
        return {}
    value = source.get("clone_as_skill")
    if type(value) is not bool:
        raise ValueError("Rule version source must contain boolean clone_as_skill")
    return {"clone_as_skill": value}


def _insert_version(
    conn: Connection,
    item_type: str,
    fields: dict,
    source: dict | None = None,
    *,
    device: str = "*",
    repo: str = "*",
) -> int:
    values = {**inherited_version_metadata(item_type, source), **fields}
    values["content"] = Json(values["content"])
    item_id = _get_model(item_type).create(conn=conn, **values)
    with conn.cursor() as cur:
        if source is not None:
            _copy_configs(cur, source["id"], item_id, item_type)
        else:
            cur.execute(
                """
                INSERT INTO harness_configs (item_id, item_type, device, repo, agents, subagents, enabled, exclude)
                VALUES (%s, %s, %s, %s, %s, %s, %s, false)
                """,
                (
                    item_id,
                    item_type,
                    device,
                    repo,
                    fields["agents"],
                    fields["subagents"],
                    fields["enabled"],
                ),
            )
    return item_id


def _get_model(item_type: str):
    from services.api.models.rule import RuleModel
    from services.api.models.skill import SkillModel
    from services.api.models.tool import ToolModel
    from services.api.models.hook import HookModel
    from services.api.models.agent import AgentModel

    registry = {
        "rule": RuleModel,
        "skill": SkillModel,
        "tool": ToolModel,
        "hook": HookModel,
        "agent": AgentModel,
    }
    return registry[item_type]


def _project_filter(project: str | None) -> tuple[str, list]:
    if project is None:
        return "", []
    return "\n          AND (project IS NULL OR project = %s)", [project]


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

    project_clause, params = _project_filter(project)
    query = f"SELECT * FROM {table}\n        WHERE {latest}{project_clause}"

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


def list_items(
    item_type: str, project: str | None = None, agent: str | None = None
) -> list[dict]:
    return _list_items_internal(item_type, project, agent, enabled_only=True)


def list_items_summary(
    item_type: str,
    project: str | None = None,
    agent: str | None = None,
    *,
    sort: str = "manual",
    enabled: bool | None = None,
) -> list[dict]:
    table = _table(item_type)
    order = sort_clause(sort, HARNESS_SORTS)
    if item_type != "rule" and sort in _RULE_CLONE_SORTS:
        raise ValueError("Skill clone ordering is available only for rules")
    base_cols = (
        "id, name, project, agents, sort_key, enabled, version, created_at, updated_at"
    )
    cols = f"{base_cols}, clone_as_skill" if item_type == "rule" else base_cols

    project_clause, params = _project_filter(project)
    count_join = ""
    if sort in _CONFIG_COUNT_SORTS:
        count_join = f"""
            LEFT JOIN LATERAL (
                SELECT count(*) AS config_count FROM harness_configs
                WHERE item_type = %s AND item_id = {table}.id
            ) config_counts ON true
        """
        params.insert(0, item_type)
    query = f"""SELECT {cols} FROM (
        SELECT {cols}, MAX(version) OVER (PARTITION BY name, project) AS latest_version
        FROM {table}
    ) {table} {count_join} WHERE version = latest_version {project_clause}"""

    if agent:
        query += "\n          AND %s = ANY(agents)"
        params.append(agent)

    if enabled is not None:
        if type(enabled) is not bool:
            raise ValueError("enabled must be a boolean")
        query += "\n          AND enabled = %s"
        params.append(enabled)
    query += "\n        ORDER BY " + order

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return [_row_to_dict(r) for r in cur.fetchall()]


def list_items_full(
    item_type: str, project: str | None = None, agent: str | None = None
) -> list[dict]:
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
    assert isinstance(content, dict) and "body" in content, (
        "content must be a dict with a 'body' key."
    )
    _table(item_type)
    with harness_write(item_type) as conn:
        return _insert_version(
            conn,
            item_type,
            {
                "name": name,
                "project": project,
                "agents": _sort_optional_list(agents) or [],
                "subagents": _sort_optional_list(subagents) or [],
                "content": content,
                "sort_key": sort_key if sort_key is not None else 0,
                "enabled": enabled,
                "version": 1,
            },
        )


def update_content(item_type: str, item_id: int, content: dict) -> int:
    BaseModel._validate_id(item_id)
    assert isinstance(content, dict) and "body" in content, (
        "content must be a dict with a 'body' key."
    )
    table = _table(item_type)

    with harness_write(item_type) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {table} WHERE id = %s FOR UPDATE", (item_id,))
            source = cur.fetchone()
            assert source, f"Item not found: {item_id}"
            assert source["version"] is not None, (
                f"Item {item_id} is a proposed row (no version); promote it via the proposals service instead."
            )

            return _insert_version(
                conn,
                item_type,
                {
                    "name": source["name"],
                    "project": source["project"],
                    "agents": source["agents"],
                    "subagents": source["subagents"],
                    "content": content,
                    "sort_key": source["sort_key"],
                    "enabled": source["enabled"],
                    "version": source["version"] + 1,
                },
                source,
            )


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
        enabled=enabled,
        name=name,
        sort_key=sort_key,
        clone_as_skill=clone_as_skill,
    )
    if agents is not None:
        fields["agents"] = _sort_optional_list(agents)
    if subagents is not None:
        fields["subagents"] = _sort_optional_list(subagents)
    if project != "UNSET":
        fields["project"] = project or None

    with harness_write(item_type) as conn:
        _get_model(item_type).dynamic_update(item_id, fields, conn=conn)


def reorder_items(item_type: str, ids: list[int]) -> None:
    assert_not_empty(ids, "ids")
    table = _table(item_type)

    with harness_write(item_type) as conn:
        with conn.cursor() as cur:
            for i, item_id in enumerate(ids):
                cur.execute(
                    f"UPDATE {table} SET sort_key = %s, updated_at = now() WHERE id = %s",
                    (i, item_id),
                )


def get_version_history(
    item_type: str, name: str, project: str | None = None
) -> list[dict]:
    assert_not_empty(name, "name")
    table = _table(item_type)
    proj_clause, proj_params = _project_clause(project)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM {table} WHERE name = %s {proj_clause} AND version IS NOT NULL ORDER BY version DESC",
                [name] + proj_params,
            )
            return [_row_to_dict(r) for r in cur.fetchall()]


def get_version_history_summary(
    item_type: str, name: str, project: str | None = None
) -> list[dict]:
    assert_not_empty(name, "name")
    table = _table(item_type)
    proj_clause, proj_params = _project_clause(project)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT id, version, created_at FROM {table} WHERE name = %s {proj_clause} AND version IS NOT NULL ORDER BY version DESC",
                [name] + proj_params,
            )
            return [dict(r) for r in cur.fetchall()]


def _get_scoped_item(
    cursor, item_type: str, name: str, project: str | None, *, for_update: bool = False
) -> dict | None:
    table = _table(item_type)
    latest = _LATEST_VERSION_CLAUSE.format(table=table)
    cursor.execute(
        f"SELECT * FROM {table} WHERE name = %s AND project IS NOT DISTINCT FROM %s AND {latest}"
        + (" FOR UPDATE" if for_update else ""),
        (name, project),
    )
    row = cursor.fetchone()
    return _row_to_dict(row) if row else None


def get_item(item_type: str, name: str, project: str | None = None) -> dict | None:
    assert_not_empty(name, "name")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if project:
                row = _get_scoped_item(cur, item_type, name, project)
                if row:
                    return row
            return _get_scoped_item(cur, item_type, name, None)


def upsert_item(
    item_type: str,
    name: str,
    content: dict,
    project: str | None = None,
    agents: list[str] | None = None,
    subagents: list[str] | None = None,
    sort_key: int | None = None,
    enabled: bool = True,
    *,
    device: str = "*",
    repo: str = "*",
) -> int:
    assert_not_empty(name, "name")
    assert isinstance(content, dict) and "body" in content, (
        "content must be a dict with a 'body' key."
    )
    _table(item_type)

    agents = _sort_optional_list(agents)
    subagents = _sort_optional_list(subagents)

    with harness_write(item_type) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            existing = _get_scoped_item(cur, item_type, name, project, for_update=True)
        if existing:
            new_version = existing["version"] + 1
            # File-derived upserts cannot observe virtual agent assignments.
            preserved = set(existing.get("agents") or []) & set(VIRTUAL_AGENTS)
            if preserved:
                agents = sorted(set(agents or []) | preserved)
        else:
            new_version = 1
        return _insert_version(
            conn,
            item_type,
            {
                "name": name,
                "project": project,
                "agents": agents or [],
                "subagents": subagents or [],
                "content": content,
                "sort_key": sort_key
                if sort_key is not None
                else existing["sort_key"]
                if existing
                else 0,
                "enabled": enabled,
                "version": new_version,
            },
            existing,
            device=device,
            repo=repo,
        )


def delete_item(item_type: str, item_id: int) -> None:
    table = _table(item_type)
    with harness_write(item_type) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM harness_configs WHERE item_id = %s AND item_type = %s",
                (item_id, item_type),
            )
            cur.execute(f"DELETE FROM {table} WHERE id = %s", (item_id,))
