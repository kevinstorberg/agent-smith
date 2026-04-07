from __future__ import annotations

from psycopg2.extras import RealDictCursor

from services.db import get_connection
from services.api.models.base import BaseModel
from services.api.models.shared.harness import (
    list_items, get_item, upsert_item, content_metadata, _table, _row_to_dict,
)


class AgentModel(BaseModel):
    table = "harness_agents"
    item_type = "agent"

    @classmethod
    def _collect_scoped_items(cls, item_type, subagent_name, agent, project=None):
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

    @classmethod
    def collect_from_db(cls, agent, project=None):
        rows = list_items("agent", project=project, agent=agent)
        result = {}
        for r in rows:
            name = r["name"]
            meta = content_metadata(r)
            scoped_rules = cls._collect_scoped_items("rule", name, agent, project)
            scoped_tools = cls._collect_scoped_items("tool", name, agent, project)
            result[name] = {
                "body": r["content"]["body"],
                "metadata": meta,
                "scoped_rules": scoped_rules,
                "scoped_tools": scoped_tools,
            }
        return result


def list_agents(**kw): return list_items("agent", **kw)
def get_agent(name, **kw): return get_item("agent", name, **kw)
def upsert_agent(name, **kw): return upsert_item("agent", name, **kw)
collect_agents_from_db = AgentModel.collect_from_db
_collect_scoped_items = AgentModel._collect_scoped_items
