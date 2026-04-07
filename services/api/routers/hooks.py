from __future__ import annotations

from services.api.models.shared.harness import content_metadata
from services.api.routers.shared.base_controller import BaseHarnessRouter


class HooksRouter(BaseHarnessRouter):
    item_type = "hook"
    convenience_path = "/hooks"

    def _format_convenience_row(self, row):
        return {"name": row["name"], "config": content_metadata(row)}
