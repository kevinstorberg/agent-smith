from __future__ import annotations

from fastapi import Query

from services.api.models.shared.harness import get_item_by_id, update_metadata
from services.api.routers.shared.base_controller import BaseHarnessRouter
from services.api.routers.shared.validators import MetadataUpdate


class RulesRouter(BaseHarnessRouter):
    item_type = "rule"

    def __init__(self):
        super().__init__()
        self.router.add_api_route("/rules", self.convenience_list, methods=["GET"])

    def convenience_list(self, project: str = Query(""), agent: str = Query("")):
        rows = self._list_for_convenience(project, agent)
        return [{"name": r["name"], "content": r["content"]["body"]} for r in rows]

    def patch_metadata(self, item_id: int, body: MetadataUpdate):
        update_metadata(
            self.item_type, item_id,
            enabled=body.enabled, agents=body.agents,
            name=body.name, sort_key=body.sort_key,
            project=body.project if body.project is not None else "UNSET",
            clone_as_skill=body.clone_as_skill,
        )
        return get_item_by_id(self.item_type, item_id)
