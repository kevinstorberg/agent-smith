from __future__ import annotations

from services.api.models.shared.harness import content_metadata
from services.api.routers.shared.base_controller import BaseHarnessRouter


class SkillsRouter(BaseHarnessRouter):
    item_type = "skill"
    convenience_path = "/skills"

    def _format_convenience_row(self, row):
        meta = content_metadata(row)
        return {"name": row["name"], "content": row["content"]["body"], "files": sorted(meta.get("files", {}).keys())}
