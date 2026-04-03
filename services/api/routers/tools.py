from __future__ import annotations

from fastapi import Query

from services.api.models.shared.harness import content_metadata
from services.api.routers.shared.base_controller import BaseHarnessRouter


class ToolsRouter(BaseHarnessRouter):
    item_type = "tool"

    def __init__(self):
        super().__init__()
        self.router.add_api_route("/mcp", self.convenience_list, methods=["GET"])

    def convenience_list(self, project: str = Query(""), agent: str = Query("")):
        rows = self._list_for_convenience(project, agent)
        return [{"name": r["name"], "config": content_metadata(r)} for r in rows]
