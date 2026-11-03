from __future__ import annotations

from dataclasses import dataclass

from scripts.shared.hook_permissions import validate_managed_allow_rules
from services.api.models.base import BaseModel
from services.api.models.shared.harness import list_items, get_item, upsert_item, content_metadata


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


def map_hook_event(canonical_name: str, agent: str) -> str | None:
    agent_map = HOOK_EVENT_MAP.get(agent)
    if not agent_map:
        return None
    return agent_map.get(canonical_name)


@dataclass(frozen=True)
class HookSettings:
    hooks: dict[str, list[dict]]
    allowed_tools: list[str]


def compile_hook_settings(rows: list[dict], agent: str) -> HookSettings:
    if agent not in HOOK_EVENT_MAP:
        raise ValueError(f"Unsupported hook agent: {agent}")
    events: dict[str, list[dict]] = {}
    allowed_tools: list[str] = []
    for row in rows:
        name = row.get("name", "unnamed")
        meta = content_metadata(row)
        if not isinstance(meta, dict):
            raise ValueError(f"Hook {name}: metadata must be an object")
        if "model" in meta:
            raise ValueError(f"Hook {name}: move metadata.model into each metadata.hooks entry before Sync")
        canonical = meta.get("event")
        if not isinstance(canonical, str) or not canonical.strip():
            raise ValueError(f"Hook {name}: metadata.event must be a nonblank canonical event name")
        mapped = map_hook_event(canonical, agent)
        if not mapped:
            continue
        hooks = meta.get("hooks", [])
        if not isinstance(hooks, list) or any(not isinstance(hook, dict) for hook in hooks):
            raise ValueError(f"Hook {name}: metadata.hooks must be a list of objects")
        for index, hook in enumerate(hooks):
            if "model" in hook and (not isinstance(hook["model"], str) or not hook["model"].strip()):
                raise ValueError(f"Hook {name}: metadata.hooks[{index}].model must be a nonblank string")
        permissions = meta.get("permissions", {})
        if not isinstance(permissions, dict) or set(permissions) - {"allow"}:
            raise ValueError(f"Hook {name}: metadata.permissions must contain only an allow list")
        if permissions and agent != "claude":
            raise ValueError(f"Hook {name}: metadata.permissions is supported only for Claude")
        rules = validate_managed_allow_rules(permissions.get("allow", []), f"Hook {name}: metadata.permissions.allow")
        if hooks:
            allowed_tools.extend(rule for rule in rules if rule not in allowed_tools)
        events.setdefault(mapped, []).append({"matcher": meta.get("matcher", ""), "hooks": hooks})
    return HookSettings(hooks=events, allowed_tools=allowed_tools)


class HookModel(BaseModel):
    table = "harness_hooks"
    item_type = "hook"

    @classmethod
    def collect_from_db(cls, agent, project=None):
        return cls.collect_settings_from_db(agent, project).hooks

    @classmethod
    def collect_settings_from_db(cls, agent, project=None) -> HookSettings:
        return compile_hook_settings(list_items("hook", project=project, agent=agent), agent)


def list_hooks(**kw): return list_items("hook", **kw)
def get_hook(name, **kw): return get_item("hook", name, **kw)
def upsert_hook(name, **kw): return upsert_item("hook", name, **kw)
collect_hooks_from_db = HookModel.collect_from_db
collect_hook_settings_from_db = HookModel.collect_settings_from_db
