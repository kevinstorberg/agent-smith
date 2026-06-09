from __future__ import annotations

from sqlalchemy import delete, func, select

from db.models.agent_smith import HarnessConfig
from db.repository import BaseRepository
from src.agent_smith.constants import ITEM_MODEL_BY_TYPE
from src.agent_smith.serialization import model_to_dict, normalize_harness_row, sort_optional_list
from src.agent_smith.validation import assert_not_empty, validate_content, validate_item_type


class HarnessRepository:
    def __init__(self, session) -> None:
        self.session = session

    def model_for(self, item_type: str):
        validate_item_type(item_type)
        return ITEM_MODEL_BY_TYPE[item_type]

    async def list_items(
        self,
        item_type: str,
        *,
        project: str | None = None,
        agent: str | None = None,
        enabled_only: bool = True,
        summary: bool = False,
    ) -> list[dict]:
        model = self.model_for(item_type)
        statement = select(model).where((model.project.is_(None)) | (model.project == project))
        if enabled_only:
            statement = statement.where(model.enabled.is_(True))
        if agent:
            statement = statement.where(model.agents.any(agent))
        statement = statement.order_by(model.sort_key, model.id)
        result = await self.session.execute(statement)
        rows = [normalize_harness_row(model_to_dict(row)) for row in result.scalars().all()]
        rows = self._latest_rows(rows)
        if project is not None:
            rows = self._apply_project_override(rows)
        rows = sorted(rows, key=lambda row: row["sort_key"])
        if summary:
            base = {"id", "name", "project", "agents", "sort_key", "enabled", "version", "created_at", "updated_at"}
            if item_type == "rule":
                base.add("clone_as_skill")
            rows = [{key: row[key] for key in row if key in base} for row in rows]
        return rows

    async def get_by_id(self, item_type: str, item_id: int, *, include_configs: bool = True) -> dict | None:
        model = self.model_for(item_type)
        item = await self.session.get(model, item_id)
        if item is None:
            return None
        row = normalize_harness_row(model_to_dict(item))
        if include_configs:
            row["configs"] = await self.list_configs(item_id, item_type)
        return row

    async def get_by_name(self, item_type: str, name: str, *, project: str | None = None) -> dict | None:
        assert_not_empty(name, "name")
        candidates = await self.list_items(item_type, project=project, enabled_only=False)
        if project is not None:
            for row in candidates:
                if row["name"] == name and row["project"] == project:
                    row["configs"] = await self.list_configs(row["id"], item_type)
                    return row
        for row in candidates:
            if row["name"] == name and row["project"] is None:
                row["configs"] = await self.list_configs(row["id"], item_type)
                return row
        return None

    async def create_item(
        self,
        item_type: str,
        *,
        name: str,
        content: dict,
        project: str | None = None,
        agents: list[str] | None = None,
        subagents: list[str] | None = None,
        sort_key: int | None = None,
        enabled: bool = True,
        version: int = 1,
        create_default_config: bool = True,
    ) -> int:
        validate_content(content)
        model = self.model_for(item_type)
        item = model(
            name=name,
            project=project,
            agents=sort_optional_list(agents) or [],
            subagents=sort_optional_list(subagents) or [],
            content=content,
            sort_key=sort_key if sort_key is not None else 0,
            enabled=enabled,
            version=version,
        )
        self.session.add(item)
        await self.session.flush()
        if create_default_config:
            await self.create_config(
                item_id=item.id,
                item_type=item_type,
                agents=item.agents,
                subagents=item.subagents,
                enabled=enabled,
            )
        return item.id

    async def update_content(self, item_type: str, item_id: int, content: dict) -> int:
        validate_content(content)
        model = self.model_for(item_type)
        source = await self.session.get(model, item_id)
        if source is None:
            raise KeyError(f"Item not found: {item_id}")
        item = model(
            name=source.name,
            project=source.project,
            agents=source.agents,
            subagents=source.subagents,
            content=content,
            sort_key=source.sort_key,
            enabled=source.enabled,
            version=source.version + 1,
        )
        self.session.add(item)
        await self.session.flush()
        await self.copy_configs(source_item_id=item_id, target_item_id=item.id, item_type=item_type)
        return item.id

    async def update_metadata(self, item_type: str, item_id: int, **fields) -> None:
        model = self.model_for(item_type)
        item = await self.session.get(model, item_id)
        if item is None:
            raise KeyError(f"Item not found: {item_id}")
        for key, value in fields.items():
            if key == "project":
                if value == "UNSET":
                    continue
                item.project = value or None
                continue
            if value is None:
                continue
            if key in {"agents", "subagents"}:
                value = sort_optional_list(value)
            setattr(item, key, value)

    async def upsert_item(
        self,
        item_type: str,
        *,
        name: str,
        content: dict,
        project: str | None = None,
        agents: list[str] | None = None,
        subagents: list[str] | None = None,
        sort_key: int | None = None,
        enabled: bool = True,
    ) -> int:
        existing = await self.get_by_name(item_type, name, project=project)
        return await self.create_item(
            item_type,
            name=name,
            content=content,
            project=project,
            agents=agents,
            subagents=subagents,
            sort_key=sort_key,
            enabled=enabled,
            version=(existing["version"] + 1) if existing else 1,
            create_default_config=existing is None,
        )

    async def delete_item(self, item_type: str, item_id: int) -> None:
        model = self.model_for(item_type)
        await self.session.execute(
            delete(HarnessConfig).where(HarnessConfig.item_id == item_id, HarnessConfig.item_type == item_type)
        )
        item = await self.session.get(model, item_id)
        if item is not None:
            await self.session.delete(item)

    async def reorder_items(self, item_type: str, ids: list[int]) -> None:
        model = self.model_for(item_type)
        for index, item_id in enumerate(ids):
            item = await self.session.get(model, item_id)
            if item is not None:
                item.sort_key = index

    async def history(
        self, item_type: str, *, name: str, project: str | None = None, summary: bool = True
    ) -> list[dict]:
        model = self.model_for(item_type)
        statement = select(model).where(model.name == name)
        statement = statement.where(model.project.is_(None) if project is None else model.project == project)
        statement = statement.order_by(model.version.desc())
        result = await self.session.execute(statement)
        rows = [normalize_harness_row(model_to_dict(row)) for row in result.scalars().all()]
        if summary:
            return [{"id": row["id"], "version": row["version"], "created_at": row["created_at"]} for row in rows]
        return rows

    async def list_configs(self, item_id: int, item_type: str) -> list[dict]:
        statement = (
            select(HarnessConfig)
            .where(HarnessConfig.item_id == item_id, HarnessConfig.item_type == item_type)
            .order_by(HarnessConfig.id)
        )
        result = await self.session.execute(statement)
        return [normalize_harness_row(model_to_dict(row)) for row in result.scalars().all()]

    async def batch_list_configs(self, item_ids: list[int], item_type: str) -> dict[int, list[dict]]:
        if not item_ids:
            return {}
        statement = (
            select(HarnessConfig)
            .where(HarnessConfig.item_id.in_(item_ids), HarnessConfig.item_type == item_type)
            .order_by(HarnessConfig.id)
        )
        result = await self.session.execute(statement)
        grouped: dict[int, list[dict]] = {item_id: [] for item_id in item_ids}
        for row in result.scalars().all():
            grouped.setdefault(row.item_id, []).append(normalize_harness_row(model_to_dict(row)))
        return grouped

    async def create_config(
        self,
        *,
        item_id: int,
        item_type: str,
        device: str = "*",
        repo: str = "*",
        agents: list[str] | None = None,
        subagents: list[str] | None = None,
        enabled: bool = True,
        exclude: bool = False,
    ) -> int:
        config = HarnessConfig(
            item_id=item_id,
            item_type=item_type,
            device=device,
            repo=repo,
            agents=sort_optional_list(agents) or ["claude", "codex", "gemini"],
            subagents=sort_optional_list(subagents) or [],
            enabled=enabled,
            exclude=exclude,
        )
        self.session.add(config)
        await self.session.flush()
        return config.id

    async def get_config(self, config_id: int) -> dict | None:
        config = await self.session.get(HarnessConfig, config_id)
        return normalize_harness_row(model_to_dict(config)) if config else None

    async def update_config(self, config_id: int, **fields) -> None:
        config = await self.session.get(HarnessConfig, config_id)
        if config is None:
            raise KeyError(f"Config not found: {config_id}")
        for key, value in fields.items():
            if value is None:
                continue
            if key in {"agents", "subagents"}:
                value = sort_optional_list(value)
            setattr(config, key, value)

    async def delete_config(self, config_id: int) -> None:
        config = await self.session.get(HarnessConfig, config_id)
        if config is not None:
            await self.session.delete(config)

    async def copy_configs(self, *, source_item_id: int, target_item_id: int, item_type: str) -> None:
        for config in await self.list_configs(source_item_id, item_type):
            await self.create_config(
                item_id=target_item_id,
                item_type=item_type,
                device=config["device"],
                repo=config["repo"],
                agents=config["agents"],
                subagents=config["subagents"],
                enabled=config["enabled"],
                exclude=config["exclude"],
            )

    async def count(self, model) -> int:
        result = await self.session.execute(select(func.count()).select_from(model))
        return int(result.scalar_one())

    @staticmethod
    def _latest_rows(rows: list[dict]) -> list[dict]:
        latest: dict[tuple[str, str | None], dict] = {}
        for row in rows:
            key = (row["name"], row.get("project"))
            if key not in latest or row["version"] > latest[key]["version"]:
                latest[key] = row
        return list(latest.values())

    @staticmethod
    def _apply_project_override(rows: list[dict]) -> list[dict]:
        selected: dict[str, dict] = {}
        for row in rows:
            name = row["name"]
            if row.get("project") is not None:
                selected[name] = row
            elif name not in selected:
                selected[name] = row
        return list(selected.values())


class HarnessConfigRepository(BaseRepository[HarnessConfig]):
    model = HarnessConfig
