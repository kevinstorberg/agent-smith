from __future__ import annotations

import json
import shlex
from pathlib import Path

from scripts.shared.hook_utils import _expand_hook_paths
from scripts.shared.hook_permissions import validate_managed_allow_rules
from services.api.models.hook import compile_hook_settings


ARTIFACT = (
    Path(__file__).resolve().parents[1] / "docs/examples/claude_memories.metadata.json"
)


def metadata():
    return json.loads(ARTIFACT.read_text())


def test_reviewed_artifact_compiles_model_and_grants_through_consumer(monkeypatch):
    host_root = "/synthetic/checkout with spaces"
    monkeypatch.setenv("HOST_REPO_ROOT", host_root)
    compiled = compile_hook_settings(
        [{"name": "claude_memories", "content": {"metadata": metadata()}}], "claude"
    )
    hooks = _expand_hook_paths(compiled.hooks)
    rules = _expand_hook_paths({"allow": compiled.allowed_tools})["allow"]
    assert validate_managed_allow_rules(rules, "reviewed artifact") == rules
    hook = hooks["Stop"][0]["hooks"][0]
    assert (hook["type"], hook["model"], hook["timeout"]) == ("agent", "haiku", 120)
    helper_rule = next(rule for rule in rules if rule.startswith("Bash("))
    helper_prefix = helper_rule[5:-3]
    assert shlex.split(helper_prefix) == [
        f"{host_root}/.venv/bin/python",
        f"{host_root}/scripts/claude_memory_context.py",
    ]
    assert helper_prefix in hook["prompt"]
    assert "256 total embedding tokens" in hook["prompt"]
    assert "254" in hook["prompt"] and "special tokens" in hook["prompt"]
    assert (
        "Rewrite oversized drafts" in hook["prompt"]
        and "never pad short memories" in hook["prompt"]
    )
    assert {rule for rule in rules if rule.startswith("mcp__")} == {
        "mcp__memory__memory_list",
        "mcp__memory__memory_search",
        "mcp__memory__memory_add",
    }


def test_artifact_contains_only_supported_agent_configuration():
    value = metadata()
    assert set(value) == {"event", "matcher", "permissions", "hooks"}
    assert value["event"] == "stop"
    assert len(value["hooks"]) == 1
    assert set(value["hooks"][0]) == {"type", "model", "timeout", "prompt"}
    assert set(value["permissions"]) == {"allow"}


def test_artifact_requires_bounded_attempts_and_honest_coverage():
    prompt = metadata()["hooks"][0]["prompt"]
    for requirement in (
        "Stop is always allowed",
        "never return ok:false",
        "stop_hook_active",
        "at most 2 pages",
        "memory_add at most 3 times",
        "at most 6 memory_search calls",
        "verified_repo_ids",
        "SNAPSHOT",
        "Never advance a receipt after such a failure",
        "partial publication",
        "not exactly once",
        "last_assistant_message",
        "cannot justify ACK of unrelated receipt coverage",
        "redaction is incomplete",
        "record-current",
        "hook_last_assistant_message",
        "without advancing transcript coverage",
        "On caught_up or waiting",
        "current_page:true",
        "report skipped_scope",
        "Actual helper scope errors still stop without ACK",
        "personal identifiers",
        "never raw errors or evidence in commands or status",
        "HOOK_INPUT: $ARGUMENTS",
    ):
        assert requirement in prompt
    assert "--outcome OUTCOME" in prompt
    assert "--receipt RECEIPT" in prompt
    assert "--stage STAGE --error-code SAFE_CODE" in prompt
