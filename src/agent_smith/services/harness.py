from __future__ import annotations

from db.unit_of_work import UnitOfWork
from src.agent_smith.constants import ALL_AGENTS, ITEM_TYPES
from src.agent_smith.repositories.harness import HarnessRepository
from src.agent_smith.responses import paginate
from src.agent_smith.serialization import content_metadata
from src.agent_smith.validation import validate_content, validate_item_type
from src.services.application import ApplicationService

HOOK_EVENT_MAP = {
    "claude": {
        "pre_tool_use": "PreToolUse",
        "post_tool_use": "PostToolUse",
        "post_tool_use_failure": "PostToolUseFailure",
        "stop": "Stop",
        "stop_failure": "StopFailure",
        "user_prompt_submit": "UserPromptSubmit",
        "notification": "Notification",
        "session_start": "SessionStart",
        "session_end": "SessionEnd",
        "subagent_start": "SubagentStart",
        "subagent_stop": "SubagentStop",
        "permission_request": "PermissionRequest",
        "instructions_loaded": "InstructionsLoaded",
    },
    "codex": {
        "pre_tool_use": "pre_tool_use",
        "post_tool_use": "post_tool_use",
        "post_tool_use_failure": "post_tool_use_failure",
        "stop": "stop",
        "stop_failure": "stop_failure",
        "user_prompt_submit": "user_prompt_submit",
        "session_start": "session_start",
        "session_end": "session_end",
    },
    "gemini": {
        "pre_tool_use": "preToolUse",
        "post_tool_use": "postToolUse",
        "post_tool_use_failure": "postToolUseFailure",
        "stop": "stop",
        "stop_failure": "stopFailure",
        "user_prompt_submit": "userPromptSubmit",
        "session_start": "sessionStart",
        "session_end": "sessionEnd",
    },
}


class HarnessService(ApplicationService):
    async def list_page(
        self,
        uow: UnitOfWork,
        item_type: str,
        *,
        project: str | None,
        agent: str | None,
        name: str = "",
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        repo = HarnessRepository(uow.session)
        rows = await repo.list_items(item_type, project=project, agent=agent, enabled_only=False, summary=True)
        if name:
            name_lower = name.lower()
            rows = [row for row in rows if name_lower in row["name"].lower()]
        items, total = paginate(rows, offset, limit)
        configs = await repo.batch_list_configs([item["id"] for item in items], item_type)
        for item in items:
            item["configs"] = configs.get(item["id"], [])
        return items, total

    async def convenience_list(self, uow: UnitOfWork, item_type: str, *, project: str | None, agent: str | None):
        return await HarnessRepository(uow.session).list_items(item_type, project=project, agent=agent)

    async def get_item(self, uow: UnitOfWork, item_type: str, item_id: int) -> dict | None:
        return await HarnessRepository(uow.session).get_by_id(item_type, item_id)

    async def get_item_by_name(
        self, uow: UnitOfWork, item_type: str, name: str, *, project: str | None = None
    ) -> dict | None:
        return await HarnessRepository(uow.session).get_by_name(item_type, name, project=project)

    async def create_item(
        self,
        uow: UnitOfWork,
        item_type: str,
        *,
        name: str,
        content: dict,
        project: str | None,
        agents: list[str],
        subagents: list[str] | None = None,
        sort_key: int | None,
        enabled: bool,
        device: str = "*",
        repo_path: str = "*",
    ) -> dict:
        repo = HarnessRepository(uow.session)
        item_id = await repo.create_item(
            item_type,
            name=name,
            content=content,
            project=project,
            agents=agents,
            subagents=subagents,
            sort_key=sort_key,
            enabled=enabled,
        )
        if device != "*" or repo_path != "*":
            configs = await repo.list_configs(item_id, item_type)
            if configs:
                await repo.update_config(configs[0]["id"], device=device, repo=repo_path)
        return await repo.get_by_id(item_type, item_id) or {}

    async def update_content(self, uow: UnitOfWork, item_type: str, item_id: int, content: dict) -> dict:
        repo = HarnessRepository(uow.session)
        new_id = await repo.update_content(item_type, item_id, content)
        return await repo.get_by_id(item_type, new_id) or {}

    async def update_metadata(self, uow: UnitOfWork, item_type: str, item_id: int, **fields) -> dict | None:
        repo = HarnessRepository(uow.session)
        await repo.update_metadata(item_type, item_id, **fields)
        return await repo.get_by_id(item_type, item_id)

    async def history(self, uow: UnitOfWork, item_type: str, item_id: int) -> list[dict]:
        repo = HarnessRepository(uow.session)
        item = await repo.get_by_id(item_type, item_id, include_configs=False)
        if item is None:
            return []
        return await repo.history(item_type, name=item["name"], project=item.get("project"))

    async def delete_item(self, uow: UnitOfWork, item_type: str, item_id: int) -> None:
        await HarnessRepository(uow.session).delete_item(item_type, item_id)

    async def reorder_items(self, uow: UnitOfWork, item_type: str, ids: list[int]) -> None:
        await HarnessRepository(uow.session).reorder_items(item_type, ids)

    async def list_configs(self, uow: UnitOfWork, item_id: int, item_type: str) -> list[dict]:
        return await HarnessRepository(uow.session).list_configs(item_id, item_type)

    async def create_config(self, uow: UnitOfWork, item_id: int, item_type: str, **fields) -> int:
        return await HarnessRepository(uow.session).create_config(item_id=item_id, item_type=item_type, **fields)

    async def update_config(self, uow: UnitOfWork, config_id: int, **fields) -> None:
        await HarnessRepository(uow.session).update_config(config_id, **fields)

    async def delete_config(self, uow: UnitOfWork, config_id: int) -> None:
        await HarnessRepository(uow.session).delete_config(config_id)

    async def upsert_item(
        self,
        uow: UnitOfWork,
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
        validate_content(content)
        return await HarnessRepository(uow.session).upsert_item(
            item_type,
            name=name,
            content=content,
            project=project,
            agents=agents,
            subagents=subagents,
            sort_key=sort_key,
            enabled=enabled,
        )

    async def collect_rules(self, uow: UnitOfWork, agent: str, project: str | None = None) -> list[tuple[str, str]]:
        rows = await HarnessRepository(uow.session).list_items("rule", project=project, agent=agent)
        return [(row["name"], row["content"]["body"]) for row in rows]

    async def collect_skills(self, uow: UnitOfWork, agent: str, project: str | None = None) -> dict[str, dict]:
        rows = await HarnessRepository(uow.session).list_items("skill", project=project, agent=agent)
        return {
            row["name"]: {"skill_md": row["content"]["body"], "files": content_metadata(row).get("files", {})}
            for row in rows
        }

    async def collect_tools(self, uow: UnitOfWork, agent: str, project: str | None = None) -> dict[str, dict]:
        rows = await HarnessRepository(uow.session).list_items("tool", project=project, agent=agent)
        return {row["name"]: content_metadata(row) for row in rows}

    async def collect_hooks(self, uow: UnitOfWork, agent: str, project: str | None = None) -> dict[str, list[dict]]:
        rows = await HarnessRepository(uow.session).list_items("hook", project=project, agent=agent)
        events: dict[str, list[dict]] = {}
        for row in rows:
            metadata = content_metadata(row)
            mapped = HOOK_EVENT_MAP.get(agent, {}).get(metadata.get("event", ""))
            if mapped:
                events.setdefault(mapped, []).append(
                    {"matcher": metadata.get("matcher", ""), "hooks": metadata.get("hooks", [])}
                )
        return events

    async def collect_agents(self, uow: UnitOfWork, agent: str, project: str | None = None) -> dict[str, dict]:
        repo = HarnessRepository(uow.session)
        rows = await repo.list_items("agent", project=project, agent=agent)
        result = {}
        for row in rows:
            metadata = content_metadata(row)
            scoped_rules = await self._collect_scoped_items(uow, "rule", row["name"], agent, project)
            scoped_tools = await self._collect_scoped_items(uow, "tool", row["name"], agent, project)
            result[row["name"]] = {
                "body": row["content"]["body"],
                "metadata": metadata,
                "scoped_rules": scoped_rules,
                "scoped_tools": scoped_tools,
            }
        return result

    async def _collect_scoped_items(
        self, uow: UnitOfWork, item_type: str, subagent_name: str, agent: str, project: str | None
    ) -> list[dict]:
        rows = await HarnessRepository(uow.session).list_items(item_type, project=project, agent=agent)
        return [
            row for row in rows if subagent_name in (row.get("subagents") or []) or "*" in (row.get("subagents") or [])
        ]

    async def resolve_items(self, uow: UnitOfWork, items: dict) -> list[tuple[str, str]]:
        source = items.get("source")
        if source == "harness":
            harness_type = items.get("harness_type", "rule")
            agent = items.get("agent", "claude")
            exclude = set(items.get("exclude", []))
            if harness_type != "rule":
                raise ValueError(f"Unsupported harness_type: {harness_type}")
            return [(name, body) for name, body in await self.collect_rules(uow, agent) if name not in exclude]
        if source == "skill":
            skill_name = items.get("skill_name")
            if not skill_name:
                raise ValueError("skill source requires 'skill_name'")
            skill = await self.get_item_by_name(uow, "skill", skill_name)
            if not skill:
                raise ValueError(f"Skill not found in harness DB: {skill_name}")
            return [(skill_name, skill["content"]["body"])]
        raise ValueError(f"Unknown items source: {source}")

    async def seed_mcp_servers(self, uow: UnitOfWork, mcp_base: str) -> None:
        for name in ("memory", "plans", "harness", "evals", "graphs", "jobs"):
            existing = await self.get_item_by_name(uow, "tool", name)
            if existing:
                continue
            await self.upsert_item(
                uow,
                "tool",
                name=name,
                content={"body": "", "metadata": {"url": f"{mcp_base.rstrip('/')}/mcp/{name}/"}},
                agents=ALL_AGENTS,
            )


def validate_public_item_type(item_type: str) -> str:
    return validate_item_type(item_type)


def valid_item_types() -> tuple[str, ...]:
    return ITEM_TYPES
