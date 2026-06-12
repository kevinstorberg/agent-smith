from __future__ import annotations

from scripts.shared.agents import VIRTUAL_AGENTS
from services.api.models.shared.harness import content_metadata
from services.api.routers.shared.base_controller import BaseHarnessRouter
from services.config import ALL_AGENTS


class AgentsRouter(BaseHarnessRouter):
    item_type = "agent"
    convenience_path = "/agents"

    def _register_routes(self):
        self.router.add_api_route("/agents/assignable", self.list_assignable_agents, methods=["GET"])
        super()._register_routes()

    def list_assignable_agents(self):
        return {"agents": list(ALL_AGENTS), "virtual_agents": list(VIRTUAL_AGENTS)}

    def _format_convenience_row(self, row):
        return {"name": row["name"], "description": content_metadata(row).get("description", "")}
