from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from services.api.models.shared.harness import (
    list_items, list_items_summary, get_item_by_id,
    create_item, update_content, update_metadata,
    reorder_items, get_version_history_summary, delete_item,
)
from services.api.models.harness_config import (
    batch_list_configs, list_configs, create_config, update_config, delete_config,
)
from services.api.routers.base import require_found, list_response, delete_response, empty_to_none, update_fields
from services.api.routers.shared.validators import (
    CreateRequest, ContentUpdate, MetadataUpdate, ReorderRequest,
    ConfigCreate, ConfigUpdate,
)


class BaseHarnessRouter:
    item_type: str

    def __init__(self):
        self.router = APIRouter()
        self._register_routes()

    def _register_routes(self):
        t = self.item_type
        self.router.add_api_route(f"/items/{t}", self.list_items, methods=["GET"])
        self.router.add_api_route(f"/items/{t}/reorder", self.reorder, methods=["PUT"])
        self.router.add_api_route(f"/items/{t}/{{item_id}}", self.get_item, methods=["GET"])
        self.router.add_api_route(f"/items/{t}", self.create_item, methods=["POST"], status_code=201)
        self.router.add_api_route(f"/items/{t}/{{item_id}}/content", self.update_content, methods=["PUT"])
        self.router.add_api_route(f"/items/{t}/{{item_id}}", self.patch_metadata, methods=["PATCH"])
        self.router.add_api_route(f"/items/{t}/{{item_id}}/history", self.get_history, methods=["GET"])
        self.router.add_api_route(f"/items/{t}/{{item_id}}", self.delete_item, methods=["DELETE"])
        self.router.add_api_route(f"/items/{t}/{{item_id}}/configs", self.add_config, methods=["POST"], status_code=201)
        self.router.add_api_route(f"/items/{t}/{{item_id}}/configs/{{config_id}}", self.patch_config, methods=["PATCH"])
        self.router.add_api_route(f"/items/{t}/{{item_id}}/configs/{{config_id}}", self.remove_config, methods=["DELETE"])

    def _list_for_convenience(self, project: str, agent: str) -> list[dict]:
        return list_items(self.item_type, project=empty_to_none(project), agent=empty_to_none(agent))

    def list_items(
        self,
        project: str = Query(""),
        agent: str = Query(""),
        name: str = Query(""),
        limit: int = Query(10, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        all_items = list_items_summary(self.item_type, project=empty_to_none(project), agent=empty_to_none(agent))
        if name:
            name_lower = name.lower()
            all_items = [i for i in all_items if name_lower in i["name"].lower()]
        total = len(all_items)
        items = all_items[offset:offset + limit]
        configs_map = batch_list_configs([i["id"] for i in items], self.item_type)
        for item in items:
            item["configs"] = configs_map.get(item["id"], [])
        return list_response(items, total)

    def get_item(self, item_id: int):
        return require_found(get_item_by_id(self.item_type, item_id), self.item_type, item_id)

    def create_item(self, body: CreateRequest):
        try:
            item_id = create_item(
                self.item_type, body.name, body.content,
                project=body.project, agents=body.agents,
                sort_key=body.sort_key, enabled=body.enabled,
            )
            if body.device != "*" or body.repo != "*":
                configs = list_configs(item_id, self.item_type)
                if configs:
                    update_config(configs[0]["id"], device=body.device, repo=body.repo)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(409, str(e)) from e
        return get_item_by_id(self.item_type, item_id)

    def update_content(self, item_id: int, body: ContentUpdate):
        new_id = update_content(self.item_type, item_id, body.content)
        return require_found(get_item_by_id(self.item_type, new_id), self.item_type, new_id)

    def patch_metadata(self, item_id: int, body: MetadataUpdate):
        update_metadata(
            self.item_type, item_id,
            enabled=body.enabled, agents=body.agents,
            name=body.name, sort_key=body.sort_key,
            project=body.project if body.project is not None else "UNSET",
        )
        return get_item_by_id(self.item_type, item_id)

    def get_history(self, item_id: int):
        item = require_found(get_item_by_id(self.item_type, item_id), self.item_type, item_id)
        return get_version_history_summary(self.item_type, item["name"], project=item.get("project"))

    def delete_item(self, item_id: int):
        require_found(get_item_by_id(self.item_type, item_id), self.item_type, item_id)
        delete_item(self.item_type, item_id)
        return delete_response(item_id)

    def reorder(self, body: ReorderRequest):
        reorder_items(self.item_type, body.ids)
        return {"reordered": True, "count": len(body.ids)}

    def add_config(self, item_id: int, body: ConfigCreate):
        require_found(get_item_by_id(self.item_type, item_id), self.item_type, item_id)
        config_id = create_config(
            item_id, self.item_type,
            device=body.device, repo=body.repo,
            agents=body.agents, subagents=body.subagents,
            enabled=body.enabled, exclude=body.exclude,
        )
        return {"id": config_id, "item_id": item_id, "item_type": self.item_type}

    def patch_config(self, item_id: int, config_id: int, body: ConfigUpdate):
        fields = update_fields(body)
        if not fields:
            raise HTTPException(422, "No fields to update")
        update_config(config_id, **fields)
        return list_configs(item_id, self.item_type)

    def remove_config(self, item_id: int, config_id: int):
        delete_config(config_id)
        return {"deleted": config_id}
