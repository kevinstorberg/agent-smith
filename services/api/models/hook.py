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


def list_hooks(**kw): return list_items("hook", **kw)
def get_hook(name, **kw): return get_item("hook", name, **kw)
def upsert_hook(name, **kw): return upsert_item("hook", name, **kw)
collect_hooks_from_db = HookModel.collect_from_db
