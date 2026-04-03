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


list_tools = lambda **kw: list_items("tool", **kw)  # noqa: E731
get_tool = lambda name, **kw: get_item("tool", name, **kw)  # noqa: E731
upsert_tool = lambda name, **kw: upsert_item("tool", name, **kw)  # noqa: E731
collect_tools_from_db = ToolModel.collect_from_db
