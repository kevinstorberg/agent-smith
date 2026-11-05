from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from threading import Lock


_handler_lock = Lock()
_WORDS = re.compile(r"[A-Za-z][A-Za-z0-9_ -]{0,63}\Z")
_RESOURCES = {
    "memory": "MEMORY",
    "action_items": "ACTION ITEM",
    "action_item": "ACTION ITEM",
    "plans": "PLAN",
    "plan": "PLAN",
    "profiles": "PROFILE",
    "profile": "PROFILE",
    "meetings": "MEETING",
    "meeting": "MEETING",
    "jobs": "JOB",
    "job": "JOB",
    "graphs": "GRAPH",
    "graph": "GRAPH",
    "models": "MODEL",
    "model": "MODEL",
    "harness": "HARNESS",
    "rules": "HARNESS",
    "skills": "HARNESS",
    "hooks": "HARNESS",
    "tools": "HARNESS",
    "agents": "HARNESS",
    "chat": "CHAT",
    "evals": "EVAL",
    "eval_configs": "EVAL",
    "proposals": "PROPOSAL",
    "audit": "AUDIT",
    "sync": "SYNC",
    "embedding": "EMBEDDING",
    "hugging_face": "HUGGING FACE",
    "profile_topic": "PROFILE TOPIC",
    "work": "WORK",
    "http": "HTTP",
}
_CRUD = frozenset(
    {"CREATE", "READ", "LIST", "SEARCH", "UPDATE", "DELETE", "MOVE", "SAVE"}
)
_LOCAL_ACTIONS = {
    resource: _CRUD
    for resource in (
        "ACTION ITEM",
        "PLAN",
        "PROFILE",
        "PROFILE TOPIC",
        "MEETING",
        "JOB",
        "HARNESS",
        "CHAT",
        "EVAL",
        "PROPOSAL",
        "AUDIT",
    )
}
KNOWN_GRAPHS = frozenset(
    {"echo", "opinion", "improve", "chat", "meeting_ingest", "persona"}
)
_TOOL_ACTIONS = {
    "memory": {
        f"memory_{name}": ("memory", action)
        for name, action in {
            "add": "create",
            "search": "search",
            "list": "list",
            "delete": "delete",
            "update": "update",
        }.items()
    },
    "action-items": {
        f"action_item_{action}": ("action-items", action)
        for action in ("list", "get", "create", "update", "delete", "move")
    },
    "plans": {action: ("plans", action) for action in ("save", "get", "search")},
    "graphs": {"run_graph": ("graphs", "run")},
    "chat": {"chat_read": ("chat", "read"), "chat_post": ("chat", "create")},
    "harness": {
        f"harness_{name}": ("harness", action)
        for name, action in {
            "list": "list",
            "get": "get",
            "upsert": "save",
            "disable": "update",
            "sync_item": "sync",
        }.items()
    },
    "meetings": {
        f"meeting_{name}": ("meetings", action)
        for name, action in {
            "list": "list",
            "get": "get",
            "search": "search",
            "sync_status": "read",
        }.items()
    },
    "jobs": {
        f"job_{name}": ("jobs", action)
        for name, action in {
            "create": "create",
            "list": "list",
            "get": "get",
            "update": "update",
            "delete": "delete",
            "run_now": "run",
            "list_executions": "list",
            "add_config": "create",
            "update_config": "update",
            "delete_config": "delete",
        }.items()
    },
    "evals": {
        f"eval_{name}": ("evals", action)
        for name, action in {
            "suite_list": "list",
            "suite_get": "get",
            "suite_save": "save",
            "scenario_save": "save",
        }.items()
    },
    "profiles": {
        "profile_list": ("profiles", "list"),
        "profile_get": ("profiles", "get"),
        **{
            f"profile_topic_{action}": ("profile_topic", action)
            for action in ("list", "get", "create", "update", "delete", "move")
        },
    },
}
_AGENT_ACTIONS = {
    "search_memories": ("memory", "search"),
    "search_previous_memories": ("memory", "search"),
    "get_memory": ("memory", "read"),
    "search_plans": ("plans", "search"),
    "get_plan": ("plans", "read"),
    "list_harness_items": ("harness", "list"),
    "get_harness_item": ("harness", "read"),
    "list_background_jobs": ("jobs", "list"),
    "file_proposal": ("proposals", "create"),
    "search_summary": ("meetings", "search"),
    "search_transcript": ("meetings", "search"),
    "search_known_profiles": ("profiles", "search"),
    "search_profiles": ("profiles", "search"),
    "get_profile": ("profiles", "read"),
    "get_observations": ("profiles", "read"),
    "stage_memories": ("memory", "stage"),
    "stage_labels": ("meetings", "stage"),
    "stage_profiles": ("profiles", "stage"),
    "stage_speakers": ("meetings", "stage"),
    "stage_assessment": ("profiles", "stage"),
}
_MODEL_PROVIDERS = frozenset(
    {
        "openai",
        "anthropic",
        "bedrock",
        "azure_openai",
        "gemini",
        "kimi",
        "grok",
        "deepseek",
        "openrouter",
    }
)
_PINECONE_OPERATIONS = frozenset(
    {
        "has_index",
        "create_index",
        "describe_index",
        "delete_index",
        "list_indexes",
        "configure_index",
        "query",
        "upsert",
        "fetch",
        "update",
        "delete",
        "describe_index_stats",
        "list_paginated",
    }
)


def _words(value: str, fallback: str) -> str:
    if not isinstance(value, str) or not _WORDS.fullmatch(value):
        return fallback
    return " ".join(value.replace("_", " ").replace("-", " ").upper().split())


def resource_name(value: str) -> str:
    key = (
        value.lower().replace("-", "_").replace(" ", "_")
        if isinstance(value, str)
        else ""
    )
    return _RESOURCES.get(key, "TOOL")


@dataclass(frozen=True)
class ActionLabel:
    resource: str
    action: str
    billing: str

    def __post_init__(self) -> None:
        if self.billing not in {"billable", "nonbillable", "unknown"}:
            raise ValueError("Action billing must be billable, nonbillable or unknown")
        if any(
            not isinstance(word, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9]*(?: [A-Z0-9]+)*", word)
            for word in (self.resource, self.action)
        ):
            raise ValueError("Action labels must contain controlled uppercase words")

    @property
    def prefix(self) -> str:
        marker = {
            "billable": "BILLABLE",
            "nonbillable": "NONBILLABLE",
            "unknown": "BILLABLE?",
        }[self.billing]
        return f"{self.resource} {self.action} [{marker}]"


def action_label(
    resource: str,
    action: str,
    *,
    memory_backend: str | None = None,
    graph_type: str | None = None,
    local_only: bool = False,
) -> ActionLabel:
    name, verb = resource_name(resource), _words(action, "CALL")
    verb = {"GET": "READ", "ADD": "CREATE"}.get(verb, verb)
    billing = "unknown"
    if name == "MEMORY" and verb in _CRUD:
        billing = {
            "pinecone": "billable",
            "lancedb": "nonbillable",
            "pgvector": "nonbillable",
        }.get(memory_backend, "unknown")
    elif verb in _LOCAL_ACTIONS.get(name, ()) or (
        name == "EMBEDDING" and verb in {"QUERY", "DOCUMENTS"}
    ):
        billing = "nonbillable"
    elif (name, verb) in {
        ("MEMORY", "STAGE"),
        ("MEETING", "STAGE"),
        ("PROFILE", "STAGE"),
        ("HARNESS", "SYNC"),
    }:
        billing = "nonbillable"
    elif name == "GRAPH" and verb == "RUN":
        billing = (
            "nonbillable"
            if graph_type == "echo"
            else "billable"
            if graph_type in KNOWN_GRAPHS
            else "unknown"
        )
    elif (name, verb) == ("MODEL", "GENERATE"):
        billing = "billable"
    elif (name, verb) in {("HUGGING FACE", "LOAD"), ("AUDIT", "INGEST")}:
        billing = "nonbillable" if local_only else "unknown"
    return ActionLabel(name, verb, billing)


def tool_action(namespace: str, name: str) -> tuple[str, str]:
    return _TOOL_ACTIONS.get(namespace, {}).get(name, ("tool", _words(name, "CALL")))


def agent_action(name: str) -> tuple[str, str]:
    return _AGENT_ACTIONS.get(name, ("tool", _words(name, "CALL")))


def provider_label(provider: str, operation: str) -> ActionLabel:
    if (provider, operation) == ("aws_cost_explorer", "get_cost_and_usage"):
        return ActionLabel("AWS COST EXPLORER", "READ", "billable")
    if (provider, operation) == ("aws_sts", "get_caller_identity"):
        return ActionLabel("AWS IDENTITY", "READ", "nonbillable")
    if provider in _MODEL_PROVIDERS:
        return action_label("model", "generate")
    if provider == "pinecone":
        return ActionLabel(
            "PINECONE",
            _words(operation, "CALL"),
            "billable" if operation in _PINECONE_OPERATIONS else "unknown",
        )
    if provider == "granola":
        known = {"list_notes", "get_note", "get_transcript"}
        return ActionLabel(
            "GRANOLA",
            _words(operation, "CALL"),
            "billable" if operation in known else "unknown",
        )
    if provider == "command":
        return ActionLabel("COMMAND", "RUN", "unknown")
    if provider in {"ollama", "local", "litellm", "portkey", "deepeval"}:
        return ActionLabel("MODEL", "GENERATE", "unknown")
    return ActionLabel("PROVIDER", "CALL", "unknown")


def write_log(
    record: dict,
    prefix: str,
    target_logger: logging.Logger,
    extra_name: str,
    *,
    level: int = logging.INFO,
) -> None:
    # Standalone hooks and CLI providers also need visible stderr without app handlers.
    with _handler_lock:
        if not target_logger.hasHandlers():
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            target_logger.addHandler(handler)
            target_logger.propagate = False
    target_logger.log(
        level,
        "%s %s",
        prefix,
        json.dumps(record, ensure_ascii=True, sort_keys=True),
        extra={extra_name: record},
    )
