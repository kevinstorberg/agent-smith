from __future__ import annotations

from services.api.models.base import BaseModel
from services.api.models.shared.harness import list_items, get_item, upsert_item, content_metadata


class SkillModel(BaseModel):
    table = "harness_skills"
    item_type = "skill"

    @classmethod
    def collect_from_db(cls, agent, project=None):
        rows = list_items("skill", project=project, agent=agent)
        result = {}
        for r in rows:
            meta = content_metadata(r)
            result[r["name"]] = {
                "skill_md": r["content"]["body"],
                "files": meta.get("files", {}),
            }
        return result


list_skills = lambda **kw: list_items("skill", **kw)  # noqa: E731
get_skill = lambda name, **kw: get_item("skill", name, **kw)  # noqa: E731
upsert_skill = lambda name, **kw: upsert_item("skill", name, **kw)  # noqa: E731
collect_skills_from_db = SkillModel.collect_from_db
