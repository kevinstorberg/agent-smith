from __future__ import annotations

from services.api.models.base import BaseModel
from services.api.models.shared.harness import list_items, get_item, upsert_item


class RuleModel(BaseModel):
    table = "harness_rules"
    item_type = "rule"

    @classmethod
    def collect_from_db(cls, agent, project=None):
        rows = list_items("rule", project=project, agent=agent)
        return [(r["name"], r["content"]["body"]) for r in rows]


list_rules = lambda **kw: list_items("rule", **kw)  # noqa: E731
get_rule = lambda name, **kw: get_item("rule", name, **kw)  # noqa: E731
upsert_rule = lambda name, **kw: upsert_item("rule", name, **kw)  # noqa: E731
collect_rules_from_db = RuleModel.collect_from_db
