from __future__ import annotations

from fastapi import Query

from services.api.models.shared.harness import content_metadata
from services.api.routers.shared.base_controller import BaseHarnessRouter


class SkillsRouter(BaseHarnessRouter):
    item_type = "skill"

    def __init__(self):
        super().__init__()
        self.router.add_api_route("/skills", self.convenience_list, methods=["GET"])

    def convenience_list(self, project: str = Query(""), agent: str = Query("")):
        rows = self._list_for_convenience(project, agent)
        result = []
        for r in rows:
            meta = content_metadata(r)
            files = sorted(meta.get("files", {}).keys())
            result.append({"name": r["name"], "content": r["content"]["body"], "files": files})
        return result
