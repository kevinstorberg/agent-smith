from __future__ import annotations

from services.api.models.base import BaseModel
from services.api.models.shared.harness import list_items, get_item, upsert_item, content_metadata


class ToolModel(BaseModel):
    table = "harness_tools"
    item_type = "tool"

    @classmethod
    def collect_from_db(cls, agent, project=None):
        rows = list_items("tool", project=project, agent=agent)
        return {r["name"]: content_metadata(r) for r in rows}


def list_tools(**kw): return list_items("tool", **kw)
def get_tool(name, **kw): return get_item("tool", name, **kw)
def upsert_tool(name, **kw): return upsert_item("tool", name, **kw)
collect_tools_from_db = ToolModel.collect_from_db
