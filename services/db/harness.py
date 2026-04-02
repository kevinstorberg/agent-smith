from __future__ import annotations

from psycopg2.extras import Json, RealDictCursor

from scripts.shared.validation import assert_not_empty
from services.db import get_connection
from services.db.base_model import BaseModel

def content_metadata(item: dict) -> dict:
    return item.get("content", {}).get("metadata", {})


VALID_TABLES = {
    "rule": "harness_rules",
    "skill": "harness_skills",
    "tool": "harness_tools",
    "hook": "harness_hooks",
    "agent": "harness_agents",
}

HOOK_EVENT_MAP = {
    "claude": {
        "pre_tool_use": "PreToolUse",
        "post_tool_use": "PostToolUse",
        "post_tool_use_failure": "PostToolUseFailure",
        "stop": "Stop",
        "stop_failure": "StopFailure",
        "user_prompt_submit": "UserPromptSubmit",
        "notification": "Notification",
        "session_start": "SessionStart",
        "session_end": "SessionEnd",
        "subagent_start": "SubagentStart",
        "subagent_stop": "SubagentStop",
        "permission_request": "PermissionRequest",
        "instructions_loaded": "InstructionsLoaded",
    },
}

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


def list_items_full(item_type: str, project: str | None = None, agent: str | None = None) -> list[dict]:
    return _list_items_internal(item_type, project, agent, enabled_only=False)


def get_item_by_id(item_type: str, item_id: int) -> dict | None:
    assert item_id > 0, "item_id must be positive."
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
            result["configs"] = [_config_row_to_dict(r) for r in cur.fetchall()]
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
    assert item_id > 0, "item_id must be positive."
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
            return cur.fetchone()["id"]


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
    table = _table(item_type)

    fields: dict = {}
    if enabled is not None:
        fields["enabled"] = enabled
    if agents is not None:
        fields["agents"] = _sort_optional_list(agents)
    if subagents is not None:
        fields["subagents"] = _sort_optional_list(subagents)
    if name is not None:
        fields["name"] = name
    if sort_key is not None:
        fields["sort_key"] = sort_key
    if project != "UNSET":
        fields["project"] = project or None
    if clone_as_skill is not None:
        fields["clone_as_skill"] = clone_as_skill

    model = type("_HarnessModel", (BaseModel,), {"table": table})
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

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if project is None:
                cur.execute(
                    f"SELECT * FROM {table} WHERE name = %s AND project IS NULL ORDER BY version DESC",
                    (name,),
                )
            else:
                cur.execute(
                    f"SELECT * FROM {table} WHERE name = %s AND project = %s ORDER BY version DESC",
                    (name, project),
                )
            return [_row_to_dict(r) for r in cur.fetchall()]


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


def map_hook_event(canonical_name: str, agent: str) -> str | None:
    agent_map = HOOK_EVENT_MAP.get(agent)
    if not agent_map:
        return None
    return agent_map.get(canonical_name)


def list_rules(**kwargs) -> list[dict]:
    return list_items("rule", **kwargs)

def get_rule(name: str, **kwargs) -> dict | None:
    return get_item("rule", name, **kwargs)

def upsert_rule(name: str, **kwargs) -> int:
    return upsert_item("rule", name, **kwargs)

def list_skills(**kwargs) -> list[dict]:
    return list_items("skill", **kwargs)

def get_skill(name: str, **kwargs) -> dict | None:
    return get_item("skill", name, **kwargs)

def upsert_skill(name: str, **kwargs) -> int:
    return upsert_item("skill", name, **kwargs)

def list_tools(**kwargs) -> list[dict]:
    return list_items("tool", **kwargs)

def get_tool(name: str, **kwargs) -> dict | None:
    return get_item("tool", name, **kwargs)

def upsert_tool(name: str, **kwargs) -> int:
    return upsert_item("tool", name, **kwargs)

def list_hooks(**kwargs) -> list[dict]:
    return list_items("hook", **kwargs)

def get_hook(name: str, **kwargs) -> dict | None:
    return get_item("hook", name, **kwargs)

def upsert_hook(name: str, **kwargs) -> int:
    return upsert_item("hook", name, **kwargs)

def list_agents(**kwargs) -> list[dict]:
    return list_items("agent", **kwargs)

def get_agent(name: str, **kwargs) -> dict | None:
    return get_item("agent", name, **kwargs)

def upsert_agent(name: str, **kwargs) -> int:
    return upsert_item("agent", name, **kwargs)


def delete_item(item_type: str, item_id: int) -> None:
    table = _table(item_type)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM harness_configs WHERE item_id = %s AND item_type = %s",
                (item_id, item_type),
            )
            cur.execute(f"DELETE FROM {table} WHERE id = %s", (item_id,))


def collect_rules_from_db(agent: str, project: str | None = None) -> list[tuple[str, str]]:
    rows = list_items("rule", project=project, agent=agent)
    return [(r["name"], r["content"]["body"]) for r in rows]


def collect_skills_from_db(agent: str, project: str | None = None) -> dict[str, dict]:
    rows = list_items("skill", project=project, agent=agent)
    result = {}
    for r in rows:
        meta = content_metadata(r)
        result[r["name"]] = {
            "skill_md": r["content"]["body"],
            "files": meta.get("files", {}),
        }
    return result


def collect_tools_from_db(agent: str, project: str | None = None) -> dict[str, dict]:
    rows = list_items("tool", project=project, agent=agent)
    return {r["name"]: content_metadata(r) for r in rows}


def collect_hooks_from_db(agent: str, project: str | None = None) -> dict[str, list[dict]]:
    rows = list_items("hook", project=project, agent=agent)
    events: dict[str, list[dict]] = {}
    for r in rows:
        meta = content_metadata(r)
        canonical = meta.get("event", "")
        mapped = map_hook_event(canonical, agent)
        if not mapped:
            continue
        events.setdefault(mapped, []).append({
            "matcher": meta.get("matcher", ""),
            "hooks": meta.get("hooks", []),
        })
    return events


def _collect_scoped_items(
    item_type: str, subagent_name: str, agent: str, project: str | None = None,
) -> list[dict]:
    table = _table(item_type)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM {table} WHERE enabled = true "
                f"AND (%s = ANY(subagents) OR '*' = ANY(subagents)) "
                f"AND %s = ANY(agents) "
                f"ORDER BY sort_key",
                (subagent_name, agent),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]


def collect_agents_from_db(agent: str, project: str | None = None) -> dict[str, dict]:
    rows = list_items("agent", project=project, agent=agent)
    result = {}
    for r in rows:
        name = r["name"]
        meta = content_metadata(r)
        scoped_rules = _collect_scoped_items("rule", name, agent, project)
        scoped_tools = _collect_scoped_items("tool", name, agent, project)
        result[name] = {
            "body": r["content"]["body"],
            "metadata": meta,
            "scoped_rules": scoped_rules,
            "scoped_tools": scoped_tools,
        }
    return result


# ---------------------------------------------------------------------------
# harness_configs CRUD
# ---------------------------------------------------------------------------

def list_configs(item_id: int, item_type: str) -> list[dict]:
    assert item_id > 0, "item_id must be positive."
    _table(item_type)  # validate item_type
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM harness_configs WHERE item_id = %s AND item_type = %s ORDER BY id",
                (item_id, item_type),
            )
            return [_config_row_to_dict(r) for r in cur.fetchall()]


def create_config(
    item_id: int,
    item_type: str,
    device: str = "*",
    repo: str = "*",
    agents: list[str] | None = None,
    subagents: list[str] | None = None,
    enabled: bool = True,
    exclude: bool = False,
) -> int:
    assert item_id > 0, "item_id must be positive."
    _table(item_type)  # validate item_type
    agents = _sort_optional_list(agents)
    subagents = _sort_optional_list(subagents)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO harness_configs (item_id, item_type, device, repo, agents, subagents, enabled, exclude)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (item_id, item_type, device, repo, agents or [], subagents or [], enabled, exclude),
            )
            return cur.fetchone()[0]


def update_config(config_id: int, **fields) -> None:
    assert config_id > 0, "config_id must be positive."
    assert fields, "At least one field must be provided."

    sets, params = [], []
    for col, val in fields.items():
        if col in ("agents", "subagents"):
            val = _sort_optional_list(val)
        sets.append(f"{col} = %s")
        params.append(val)

    sets.append("updated_at = now()")
    params.append(config_id)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE harness_configs SET {', '.join(sets)} WHERE id = %s",
                params,
            )


def delete_config(config_id: int) -> None:
    assert config_id > 0, "config_id must be positive."
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM harness_configs WHERE id = %s", (config_id,))


_config_row_to_dict = _row_to_dict


# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

def resolve_sync_targets(item: dict, agent: str, device_name: str) -> list[str]:
    """Returns repo targets ('*' for global, absolute paths for repo-local, empty for no sync).

    Configs are the sole authority — legacy item columns are not consulted.
    """
    configs = item.get("configs", [])
    relevant = [
        c for c in configs
        if c["enabled"]
        and agent in c["agents"]
        and _device_matches(c["device"], device_name)
    ]

    additive = [c for c in relevant if not c["exclude"]]
    subtractive = [c for c in relevant if c["exclude"]]

    if not additive:
        return []

    targets = {c["repo"] for c in additive}

    for c in subtractive:
        targets.discard(c["repo"])

    return sorted(targets)


def _device_matches(config_device: str, device_name: str) -> bool:
    if config_device == "*":
        return True
    if not device_name:
        return False
    return config_device == device_name
