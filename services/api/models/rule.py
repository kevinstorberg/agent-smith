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


def list_rules(**kw): return list_items("rule", **kw)
def get_rule(name, **kw): return get_item("rule", name, **kw)
def upsert_rule(name, **kw): return upsert_item("rule", name, **kw)
collect_rules_from_db = RuleModel.collect_from_db
