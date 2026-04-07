from __future__ import annotations

from services.api.models.shared.harness import get_item_by_id, update_metadata
from services.api.routers.base import resolve_project
from services.api.routers.shared.base_controller import BaseHarnessRouter
from services.api.routers.shared.validators import MetadataUpdate


class RulesRouter(BaseHarnessRouter):
    item_type = "rule"
    convenience_path = "/rules"

    def _format_convenience_row(self, row):
        return {"name": row["name"], "content": row["content"]["body"]}

    def patch_metadata(self, item_id: int, body: MetadataUpdate):
        update_metadata(
            self.item_type, item_id,
            enabled=body.enabled, agents=body.agents,
            name=body.name, sort_key=body.sort_key,
            project=resolve_project(body.project),
            clone_as_skill=body.clone_as_skill,
        )
        return get_item_by_id(self.item_type, item_id)
