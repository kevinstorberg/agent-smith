from __future__ import annotations

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
}


def map_hook_event(canonical_name: str, agent: str) -> str | None:
    agent_map = HOOK_EVENT_MAP.get(agent)
    if not agent_map:
        return None
    return agent_map.get(canonical_name)


class HookModel(BaseModel):
    table = "harness_hooks"
    item_type = "hook"

    @classmethod
    def collect_from_db(cls, agent, project=None):
        rows = list_items("hook", project=project, agent=agent)
        events: dict[str, list[dict]] = {}
        for r in rows:
            meta = content_metadata(r)
            canonical = meta.get("event", "")
            mapped = map_hook_event(canonical, agent)
            if not mapped:
                continue
            events.setdefault(mapped, []).append({
                "matcher": meta.get("matcher", ""),
                "hooks": meta.get("hooks", []),
            })
        return events


list_hooks = lambda **kw: list_items("hook", **kw)  # noqa: E731
get_hook = lambda name, **kw: get_item("hook", name, **kw)  # noqa: E731
upsert_hook = lambda name, **kw: upsert_item("hook", name, **kw)  # noqa: E731
collect_hooks_from_db = HookModel.collect_from_db
