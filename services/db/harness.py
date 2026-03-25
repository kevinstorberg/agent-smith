from __future__ import annotations

from psycopg2.extras import Json, RealDictCursor

from services.db import get_connection

VALID_TABLES = {
    "rule": "harness_rules",
    "skill": "harness_skills",
    "tool": "harness_tools",
    "hook": "harness_hooks",
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


def _table(item_type: str) -> str:
    assert item_type in VALID_TABLES, f"Invalid type: {item_type}. Must be one of {set(VALID_TABLES)}."
    return VALID_TABLES[item_type]


def _row_to_dict(row: dict) -> dict:
    result = dict(row)
    if result.get("agents") is not None:
        result["agents"] = sorted(result["agents"])
    return result


def list_items(item_type: str, project: str | None = None, agent: str | None = None) -> list[dict]:
    table = _table(item_type)

    query = f"""
        SELECT * FROM {table}
        WHERE enabled = true
          AND (project IS NULL OR project = %s)
    """
    params: list = [project]

    if agent:
        query += " AND %s = ANY(agents)"
        params.append(agent)

    query += " ORDER BY sort_key"

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            rows = [_row_to_dict(r) for r in cur.fetchall()]

    if project is None:
        return rows

    # Project-scoped items override shared items by name
    seen = {}
    for row in rows:
        name = row["name"]
        if row["project"] is not None:
            seen[name] = row
        elif name not in seen:
            seen[name] = row

    return sorted(seen.values(), key=lambda r: r["sort_key"])


def get_item(item_type: str, name: str, project: str | None = None) -> dict | None:
    assert name, "name must not be empty."
    table = _table(item_type)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Prefer project-scoped, fall back to shared
            if project:
                cur.execute(f"SELECT * FROM {table} WHERE name = %s AND project = %s", (name, project))
                row = cur.fetchone()
                if row:
                    return _row_to_dict(row)

            cur.execute(f"SELECT * FROM {table} WHERE name = %s AND project IS NULL", (name,))
            row = cur.fetchone()
            return _row_to_dict(row) if row else None


def upsert_item(
    item_type: str,
    name: str,
    content: dict,
    project: str | None = None,
    agents: list[str] | None = None,
    sort_key: str | None = None,
    enabled: bool = True,
) -> int:
    assert name, "name must not be empty."
    assert isinstance(content, dict) and "body" in content, "content must be a dict with a 'body' key."
    table = _table(item_type)

    if agents is not None:
        agents = sorted(agents)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {table} (name, project, agents, content, sort_key, enabled)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (name, project) DO UPDATE SET
                    content = EXCLUDED.content,
                    agents = EXCLUDED.agents,
                    sort_key = EXCLUDED.sort_key,
                    enabled = EXCLUDED.enabled,
                    version = {table}.version + 1,
                    updated_at = now()
                RETURNING id
                """,
                (name, project, agents, Json(content), sort_key or name, enabled),
            )
            return cur.fetchone()[0]


def map_hook_event(canonical_name: str, agent: str) -> str | None:
    agent_map = HOOK_EVENT_MAP.get(agent)
    if not agent_map:
        return None
    return agent_map.get(canonical_name)


# Convenience wrappers — one per table type

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


# --- Sync-oriented collect functions ---
# These return data in the shapes the sync pipeline expects.

def collect_rules_from_db(
    agent: str,
    project: str | None = None,
) -> list[tuple[str, str]]:
    """Returns [(name, markdown_body), ...] ordered by sort_key."""
    rows = list_items("rule", project=project, agent=agent)
    return [(r["name"], r["content"]["body"]) for r in rows]


def collect_skills_from_db(
    agent: str,
    project: str | None = None,
) -> dict[str, dict]:
    """Returns {skill_name: {"skill_md": str, "files": {path: content}}}."""
    rows = list_items("skill", project=project, agent=agent)
    result = {}
    for r in rows:
        meta = r["content"].get("metadata", {})
        result[r["name"]] = {
            "skill_md": r["content"]["body"],
            "files": meta.get("files", {}),
        }
    return result


def collect_tools_from_db(
    agent: str,
    project: str | None = None,
) -> dict[str, dict]:
    """Returns {tool_name: config_dict} with env vars NOT expanded (raw)."""
    rows = list_items("tool", project=project, agent=agent)
    return {r["name"]: r["content"].get("metadata", {}) for r in rows}


def collect_hooks_from_db(
    agent: str,
    project: str | None = None,
) -> dict[str, list[dict]]:
    """Returns {agent_event_name: [hook_handlers]} grouped by mapped event."""
    rows = list_items("hook", project=project, agent=agent)
    events: dict[str, list[dict]] = {}
    for r in rows:
        meta = r["content"].get("metadata", {})
        canonical = meta.get("event", "")
        mapped = map_hook_event(canonical, agent)
        if not mapped:
            continue
        matcher = meta.get("matcher", "")
        handlers = meta.get("hooks", [])
        events.setdefault(mapped, []).append({
            "matcher": matcher,
            "hooks": handlers,
        })
    return events
