from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import tomli_w
import yaml

from db.unit_of_work import unit_of_work
from src.agent_smith.constants import ALL_AGENTS
from src.agent_smith.repositories.harness import HarnessRepository
from src.agent_smith.serialization import content_metadata
from src.agent_smith.services.harness import HOOK_EVENT_MAP, HarnessService
from src.agent_smith.sync_targets import (
    agent_targets,
    expand_env,
    read_config,
    remove_path,
    repo_config,
    write_config,
)
from src.agent_smith.validation import validate_item_type


class AgentSmithSyncService:
    async def sync_all(self, *, dry_run: bool = False) -> dict:
        logs: list[str] = []
        for agent in agent_targets():
            logs.append(f"[{agent}/rules]")
            await self.sync_rules(agent, dry_run=dry_run, logs=logs)
            logs.append(f"[{agent}/skills]")
            await self.sync_skills(agent, dry_run=dry_run, logs=logs)
            logs.append(f"[{agent}/mcp]")
            await self.sync_mcp(agent, dry_run=dry_run, logs=logs)
            logs.append(f"[{agent}/hooks]")
            await self.sync_hooks(agent, dry_run=dry_run, logs=logs)
            logs.append(f"[{agent}/agents]")
            await self.sync_agents(agent, dry_run=dry_run, logs=logs)
        return {"success": True, "stdout": "\n".join(logs) + "\n", "stderr": ""}

    async def sync_item(
        self,
        *,
        item_type: str,
        item_id: int | None = None,
        name: str | None = None,
        project: str | None = None,
        dry_run: bool = False,
    ) -> str:
        validate_item_type(item_type)
        async with unit_of_work() as uow:
            repo = HarnessRepository(uow.session)
            item = await repo.get_by_id(item_type, item_id) if item_id else None
            if item is None and name:
                item = await repo.get_by_name(item_type, name, project=project)
        if item is None:
            return f"Not found: {item_type} '{name or item_id}'"

        agents = [agent for agent in item.get("agents", []) if agent in agent_targets()]
        if not agents:
            agents = await self._agents_for_item(item_type, item)
        if not agents:
            return "No agents to sync"

        logs: list[str] = []
        for agent in agents:
            logs.append(f"[{agent}/{item_type}]")
            await self._sync_single_type(agent, item_type, dry_run=dry_run, logs=logs, single_item=item)
            if item_type == "rule" and item.get("clone_as_skill"):
                logs.append(f"[{agent}/skills (clone)]")
                await self.sync_skills(agent, dry_run=dry_run, logs=logs, single_item=item)
        return f"Synced to {len(agents)} agent(s): {', '.join(agents)}\n" + "\n".join(logs)

    async def unsync_all(self) -> list[str]:
        removed: list[str] = []
        for agent in agent_targets():
            removed.extend(await self.unsync_agent(agent))
        return removed

    async def unsync_agent(self, agent: str) -> list[str]:
        targets = agent_targets()
        if agent not in targets:
            raise ValueError(f"Unknown agent: {agent!r}. Must be one of {set(targets)}")
        config = targets[agent]
        removed: list[str] = []
        remove_path(config["rules_file"], removed)
        if "rules_dir" in config:
            remove_path(config["rules_dir"], removed, tree=True)
        remove_path(config["skills_dir"], removed, tree=True)
        if "agents_dir" in config:
            remove_path(config["agents_dir"], removed, tree=True)

        mcp_file = Path(config["mcp_file"]).expanduser()
        if mcp_file.exists():
            data = read_config(mcp_file, config["mcp_format"])
            if config["mcp_key"] in data:
                del data[config["mcp_key"]]
                write_config(mcp_file, data, config["mcp_format"])
                removed.append(f"{mcp_file} (removed {config['mcp_key']})")

        for repo_path in await self._repos_for_agent(agent):
            if not Path(repo_path).is_dir():
                continue
            repo_targets = repo_config(agent, repo_path)
            for key in ("rules_file", "rules_dir", "skills_dir", "agents_dir"):
                path = repo_targets.get(key)
                if not path:
                    continue
                candidate = Path(path)
                if candidate.is_file():
                    candidate.unlink()
                    removed.append(str(candidate))
                elif candidate.is_dir():
                    shutil.rmtree(candidate)
                    removed.append(str(candidate))
        return removed

    async def reverse_sync(self, *, agent: str | None = None, dry_run: bool = False) -> dict:
        logs: list[str] = []
        agents = [agent] if agent else list(agent_targets())
        for target_agent in agents:
            logs.append(f"\n[{target_agent}/rules]")
            rule_count = await self.import_rules(target_agent, dry_run=dry_run, logs=logs)
            logs.append(f"[{target_agent}/skills]")
            skill_count = await self.import_skills(target_agent, dry_run=dry_run, logs=logs)
            logs.append(f"[{target_agent}/tools]")
            tool_count = await self.import_tools(target_agent, dry_run=dry_run, logs=logs)
            total = rule_count + skill_count + tool_count
            logs.append(
                f"  {target_agent}: {rule_count} rules, {skill_count} skills, {tool_count} tools ({total} total)"
            )
        return {"success": True, "stdout": "\n".join(logs) + "\n", "stderr": ""}

    async def sync_rules(self, agent: str, *, dry_run: bool, logs: list[str], single_item: dict | None = None) -> None:
        config = agent_targets()[agent]
        global_rows, repo_rows = await self._resolve_and_partition("rule", agent, single_item=single_item)
        self._sync_rules_to_target(
            [(row["name"], row["content"]["body"]) for row in global_rows], config, dry_run, logs
        )

        for repo_path, rows in repo_rows.items():
            if not Path(repo_path).is_dir():
                logs.append(f"  warning: repo path does not exist, skipping: {repo_path}")
                continue
            target_config = repo_config(agent, repo_path)
            if target_config.get("rules_file"):
                self._sync_rules_to_target(
                    [(row["name"], row["content"]["body"]) for row in rows],
                    target_config,
                    dry_run,
                    logs,
                )

    async def sync_skills(self, agent: str, *, dry_run: bool, logs: list[str], single_item: dict | None = None) -> None:
        config = agent_targets()[agent]
        global_rows, repo_rows = await self._resolve_and_partition("skill", agent, single_item=single_item)
        global_clones, repo_clones = await self._collect_skill_clones(agent, single_item=single_item)
        global_skills = {**global_clones, **self._rows_to_skills(global_rows)}
        self._sync_skills_to_target(global_skills, Path(config["skills_dir"]).expanduser(), dry_run, logs)

        for repo_path in set(repo_rows) | set(repo_clones):
            if not Path(repo_path).is_dir():
                logs.append(f"  warning: repo path does not exist, skipping: {repo_path}")
                continue
            target_config = repo_config(agent, repo_path)
            if not target_config.get("skills_dir"):
                continue
            skills = {**repo_clones.get(repo_path, {}), **self._rows_to_skills(repo_rows.get(repo_path, []))}
            self._sync_skills_to_target(skills, Path(target_config["skills_dir"]), dry_run, logs)

    async def sync_agents(self, agent: str, *, dry_run: bool, logs: list[str], single_item: dict | None = None) -> None:
        config = agent_targets()[agent]
        agents_dir = config.get("agents_dir")
        if not agents_dir:
            return

        async with unit_of_work() as uow:
            agent_defs = await self._collect_agents(uow, agent)
        if single_item is not None:
            agent_defs = (
                {single_item["name"]: agent_defs[single_item["name"]]} if single_item["name"] in agent_defs else {}
            )

        dest_dir = Path(agents_dir).expanduser()
        if dry_run:
            logs.append(f"  would sync {len(agent_defs)} agent(s) -> {dest_dir}")
            return

        dest_dir.mkdir(parents=True, exist_ok=True)
        source_names = set()
        for name, data in sorted(agent_defs.items()):
            filename = f"{name}.md"
            source_names.add(filename)
            content = self._compose_agent_file(data["body"], data["metadata"], data.get("scoped_rules"))
            changed, message = self.atomic_write(dest_dir / filename, content)
            logs.append(f"  {message}")
        self._remove_stale(dest_dir, source_names, logs)

    async def sync_mcp(self, agent: str, *, dry_run: bool, logs: list[str], single_item: dict | None = None) -> None:
        config = agent_targets()[agent]
        dest = Path(config["mcp_file"]).expanduser()
        async with unit_of_work() as uow:
            servers = await HarnessRepository(uow.session).list_items("tool", agent=agent)
        if single_item is not None:
            servers = [single_item] if single_item["name"] in {row["name"] for row in servers} else []
        server_metadata = {row["name"]: expand_env(content_metadata(row)) for row in servers}

        if dry_run:
            logs.append(f"  would sync {len(server_metadata)} server(s) -> {dest}")
            return

        data = read_config(dest, config["mcp_format"]) if dest.exists() else {}
        data[config["mcp_key"]] = {
            name: config["mcp_transform"](metadata) for name, metadata in server_metadata.items()
        }
        text = tomli_w.dumps(data) if config["mcp_format"] == "toml" else json.dumps(data, indent=2) + "\n"
        _, message = self.atomic_write(dest, text)
        logs.append(f"  {message}")

    async def sync_hooks(self, agent: str, *, dry_run: bool, logs: list[str], single_item: dict | None = None) -> None:
        config = agent_targets()[agent]
        if "hooks_file" not in config:
            return
        dest = Path(config["hooks_file"]).expanduser()
        async with unit_of_work() as uow:
            hooks = await HarnessRepository(uow.session).list_items("hook", agent=agent)
            if single_item is not None:
                hooks = [single_item] if single_item["name"] in {row["name"] for row in hooks} else []
            events = await self._collect_hooks(uow, agent, hooks)

        if dry_run:
            logs.append(f"  would sync {len(events)} hook event(s) -> {dest}")
            return
        if not events:
            logs.append("  no hooks to sync")
            return

        data = read_config(dest, config["hooks_format"]) if dest.exists() else {}
        data[config["hooks_key"]] = events
        text = tomli_w.dumps(data) if config["hooks_format"] == "toml" else json.dumps(data, indent=2) + "\n"
        _, message = self.atomic_write(dest, text)
        logs.append(f"  {message}")

    async def import_rules(self, agent: str, *, dry_run: bool, logs: list[str]) -> int:
        config = agent_targets()[agent]
        count = 0
        rules_dir = Path(config.get("rules_dir", "")).expanduser() if "rules_dir" in config else None
        if rules_dir is not None and rules_dir.is_dir():
            for index, file_path in enumerate(sorted(rules_dir.glob("*.md"))):
                body = file_path.read_text(encoding="utf-8")
                await self._reverse_upsert("rule", file_path.stem, body, {}, index, dry_run, logs)
                count += 1
            return count

        rules_file = Path(config["rules_file"]).expanduser()
        if not rules_file.exists():
            return 0

        sections = re.split(r"(?=^## )", rules_file.read_text(encoding="utf-8"), flags=re.MULTILINE)
        for index, section in enumerate(filter(None, (part.strip() for part in sections))):
            match = re.match(r"^## (.+)", section)
            name = self._slugify(match.group(1)) if match else f"section_{index}"
            await self._reverse_upsert("rule", name, section, {}, index, dry_run, logs)
            count += 1
        return count

    async def import_skills(self, agent: str, *, dry_run: bool, logs: list[str]) -> int:
        skills_dir = Path(agent_targets()[agent]["skills_dir"]).expanduser()
        if not skills_dir.is_dir():
            return 0
        count = 0
        for skill_dir in sorted(path for path in skills_dir.iterdir() if path.is_dir()):
            skill_md_path = skill_dir / "SKILL.md"
            if not skill_md_path.exists():
                continue
            skill_md = skill_md_path.read_text(encoding="utf-8")
            description = self._parse_skill_frontmatter(skill_md)
            files = {}
            for file_path in sorted(skill_dir.rglob("*")):
                if file_path.is_file() and file_path.name != "SKILL.md":
                    try:
                        files[str(file_path.relative_to(skill_dir))] = file_path.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        pass
            await self._reverse_upsert(
                "skill", skill_dir.name, skill_md, {"description": description, "files": files}, None, dry_run, logs
            )
            count += 1
        return count

    async def import_tools(self, agent: str, *, dry_run: bool, logs: list[str]) -> int:
        config = agent_targets()[agent]
        mcp_file = Path(config["mcp_file"]).expanduser()
        if not mcp_file.exists():
            return 0
        servers = read_config(mcp_file, config["mcp_format"]).get(config["mcp_key"], {})
        count = 0
        for name, server_config in sorted(servers.items()):
            await self._reverse_upsert(
                "tool", name, "", self._reverse_mcp_transform(agent, server_config), None, dry_run, logs
            )
            count += 1
        return count

    async def _sync_single_type(
        self, agent: str, item_type: str, *, dry_run: bool, logs: list[str], single_item: dict
    ) -> None:
        dispatch = {
            "rule": self.sync_rules,
            "skill": self.sync_skills,
            "tool": self.sync_mcp,
            "hook": self.sync_hooks,
            "agent": self.sync_agents,
        }
        await dispatch[item_type](agent, dry_run=dry_run, logs=logs, single_item=single_item)

    async def _resolve_and_partition(
        self, item_type: str, agent: str, *, single_item: dict | None = None
    ) -> tuple[list[dict], dict[str, list[dict]]]:
        if single_item is not None:
            rows = [single_item]
        else:
            async with unit_of_work() as uow:
                rows = await HarnessRepository(uow.session).list_items(item_type, enabled_only=False)
                for row in rows:
                    row["configs"] = await HarnessRepository(uow.session).list_configs(row["id"], item_type)

        global_items: list[dict] = []
        repo_items: dict[str, list[dict]] = {}
        device_name = self._device_name()
        for row in rows:
            for target in self.resolve_sync_targets(row, agent=agent, device_name=device_name):
                if target == "*":
                    global_items.append(row)
                else:
                    repo_items.setdefault(target, []).append(row)
        return global_items, repo_items

    async def _collect_skill_clones(
        self, agent: str, *, single_item: dict | None = None
    ) -> tuple[dict[str, dict], dict[str, dict[str, dict]]]:
        global_rows, repo_rows = await self._resolve_and_partition("rule", agent, single_item=single_item)

        def to_skills(rows: list[dict]) -> dict[str, dict]:
            return {
                row["name"]: {"skill_md": row["content"]["body"], "files": {}}
                for row in rows
                if row.get("clone_as_skill")
            }

        return to_skills(global_rows), {repo: to_skills(rows) for repo, rows in repo_rows.items()}

    async def _collect_agents(self, uow, agent: str) -> dict[str, dict]:
        return await HarnessService().collect_agents(uow, agent)

    async def _collect_hooks(self, uow, agent: str, rows: list[dict]) -> dict[str, list[dict]]:
        events: dict[str, list[dict]] = {}
        for row in rows:
            metadata = content_metadata(row)
            mapped = HOOK_EVENT_MAP.get(agent, {}).get(metadata.get("event", ""))
            if mapped:
                events.setdefault(mapped, []).append(
                    {"matcher": metadata.get("matcher", ""), "hooks": metadata.get("hooks", [])}
                )
        return events

    async def _agents_for_item(self, item_type: str, item: dict) -> list[str]:
        agents = []
        for agent in agent_targets():
            targets = self.resolve_sync_targets(item, agent=agent, device_name=self._device_name())
            if targets:
                agents.append(agent)
        return agents

    async def _repos_for_agent(self, agent: str) -> list[str]:
        repos: set[str] = set()
        async with unit_of_work() as uow:
            for item_type in ("rule", "skill", "tool", "hook", "agent"):
                rows = await HarnessRepository(uow.session).list_items(item_type, enabled_only=False)
                for row in rows:
                    configs = await HarnessRepository(uow.session).list_configs(row["id"], item_type)
                    for config in configs:
                        if config["repo"] != "*" and agent in config["agents"]:
                            repos.add(config["repo"])
        return sorted(repos)

    async def _reverse_upsert(
        self,
        item_type: str,
        name: str,
        body: str,
        metadata: dict,
        sort_key: int | None,
        dry_run: bool,
        logs: list[str],
    ) -> None:
        if dry_run:
            logs.append(f"  [dry-run] {item_type}: {name}")
            return
        async with unit_of_work() as uow:
            await HarnessRepository(uow.session).upsert_item(
                item_type,
                name=name,
                content={"body": body, "metadata": metadata},
                agents=ALL_AGENTS,
                sort_key=sort_key,
            )
        logs.append(f"  {item_type}: {name}")

    @staticmethod
    def resolve_sync_targets(item: dict, agent: str, device_name: str) -> list[str]:
        relevant = [
            config
            for config in item.get("configs", [])
            if config["enabled"]
            and agent in config["agents"]
            and AgentSmithSyncService._device_matches(config["device"], device_name)
        ]
        additive = [config for config in relevant if not config["exclude"]]
        subtractive = [config for config in relevant if config["exclude"]]
        if not additive:
            return []
        targets = {config["repo"] for config in additive}
        for config in subtractive:
            targets.discard(config["repo"])
        return sorted(targets)

    @staticmethod
    def atomic_write(path: Path | str, content: str) -> tuple[bool, str]:
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_text(encoding="utf-8") == content:
            return False, f"unchanged: {path}"
        path.write_text(content, encoding="utf-8")
        return True, f"updated:   {path}"

    @staticmethod
    def _sync_rules_to_target(items: list[tuple[str, str]], config: dict, dry_run: bool, logs: list[str]) -> None:
        rules_file = Path(config["rules_file"]).expanduser()
        rules_dir = Path(config["rules_dir"]).expanduser() if "rules_dir" in config else None

        transform = None
        if rules_dir:

            def transform(text, name):
                return AgentSmithSyncService._extract_brief(text, rules_dir / f"{name}.md")

        content = AgentSmithSyncService._compose_strings(items, transform=transform)

        if dry_run:
            logs.append(f"  would compose {len(items)} file(s) -> {rules_file}")
        else:
            _, message = AgentSmithSyncService.atomic_write(rules_file, content)
            logs.append(f"  {message}")
        if rules_dir:
            AgentSmithSyncService._sync_rules_dir(items, rules_dir, dry_run, logs)

    @staticmethod
    def _sync_rules_dir(items: list[tuple[str, str]], dest_dir: Path, dry_run: bool, logs: list[str]) -> None:
        if dry_run:
            logs.append(f"  would copy {len(items)} file(s) -> {dest_dir}")
            return
        dest_dir.mkdir(parents=True, exist_ok=True)
        source_names = {f"{name}.md" for name, _ in items}
        for name, body in items:
            _, message = AgentSmithSyncService.atomic_write(dest_dir / f"{name}.md", body)
            logs.append(f"  {message}")
        AgentSmithSyncService._remove_stale(dest_dir, source_names, logs)

    @staticmethod
    def _sync_skills_to_target(skills: dict[str, dict], dest_dir: Path, dry_run: bool, logs: list[str]) -> None:
        if dry_run:
            logs.append(f"  would sync {len(skills)} skill(s) -> {dest_dir}")
            return
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name, data in sorted(skills.items()):
            dest_skill = dest_dir / name
            dest_skill.mkdir(parents=True, exist_ok=True)
            _, message = AgentSmithSyncService.atomic_write(dest_skill / "SKILL.md", data["skill_md"])
            logs.append(f"  {message}")
            for rel_path, file_content in sorted(data.get("files", {}).items()):
                dest_file = dest_skill / rel_path
                _, message = AgentSmithSyncService.atomic_write(dest_file, file_content)
                logs.append(f"  {message}")
        AgentSmithSyncService._remove_stale(dest_dir, set(skills.keys()), logs, match_dirs=True)

    @staticmethod
    def _rows_to_skills(rows: list[dict]) -> dict[str, dict]:
        result = {}
        for row in rows:
            metadata = content_metadata(row)
            result[row["name"]] = {"skill_md": row["content"]["body"], "files": metadata.get("files", {})}
        return result

    @staticmethod
    def _compose_agent_file(body: str, metadata: dict, scoped_rules: list | None = None) -> str:
        parts = []
        if metadata:
            frontmatter = yaml.dump(metadata, default_flow_style=False).rstrip()
            parts.append(f"---\n{frontmatter}\n---\n")
        parts.append(body.rstrip())
        if scoped_rules:
            parts.append("\n\n# Rules\n")
            for rule in scoped_rules:
                parts.append(rule["content"]["body"].rstrip())
        return "\n\n".join(parts) + "\n"

    @staticmethod
    def _remove_stale(dest_dir: Path, keep: set[str], logs: list[str], *, match_dirs: bool = False) -> None:
        iterator = dest_dir.iterdir() if match_dirs else dest_dir.glob("*.md")
        for stale in iterator:
            if match_dirs and not stale.is_dir():
                continue
            if stale.name not in keep:
                shutil.rmtree(stale) if stale.is_dir() else stale.unlink()
                logs.append(f"  removed:   {stale}")

    @staticmethod
    def _compose_strings(items: list[tuple[str, str]], transform=None) -> str:
        parts = []
        for name, raw in items:
            text = transform(raw.rstrip(), name) if transform else raw.rstrip()
            parts.append(text)
        return "\n\n".join(parts) + "\n"

    @staticmethod
    def _extract_brief(content: str, rules_path: Path) -> str:
        marker = "* **Your Process:**"
        if marker not in content:
            return content
        before = content.split(marker)[0].rstrip()
        return f"{before}\n* **Your Process:** See `{rules_path}`\n"

    @staticmethod
    def _reverse_mcp_transform(agent: str, server_config: dict) -> dict:
        if agent == "claude":
            keys = ("headers", "oauth")
            url = server_config.get("url", "")
        elif agent == "codex":
            keys = ("headers",)
            url = server_config.get("url", "")
        else:
            keys = ("headers",)
            url = server_config.get("httpUrl", server_config.get("url", ""))
        return {"url": url, **{key: server_config[key] for key in keys if key in server_config}}

    @staticmethod
    def _parse_skill_frontmatter(text: str) -> str:
        if not text.startswith("---"):
            return ""
        end = text.index("---", 3)
        for line in text[3:end].strip().splitlines():
            if line.startswith("description:"):
                return line.split(":", 1)[1].strip()
        return ""

    @staticmethod
    def _slugify(heading: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")

    @staticmethod
    def _device_name() -> str:
        from src.settings import get_settings

        return get_settings().DEVICE_NAME

    @staticmethod
    def _device_matches(config_device: str, device_name: str) -> bool:
        if config_device == "*":
            return True
        return bool(device_name) and config_device == device_name
