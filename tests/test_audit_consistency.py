"""Drift guards for audit knowledge that is duplicated across the host/server boundary.

The host hook (scripts/audit_hook.py) runs outside the container and cannot import
services.*, so its `cap()` logic and coding-agent list are intentional copies of the
server's. These tests fail loudly if a copy drifts — that is the single authoritative
definition of the *behavior*, even though the code cannot be physically shared.
"""
from __future__ import annotations

from pathlib import Path

import scripts.audit_hook as hook
from services.api.models.audit import AUDIT_AGENTS
from services.api.routers import audit as audit_router

CAP = hook.MAX_FIELD_CHARS

CAP_CASES = [
    "short string",
    "x" * CAP,                 # exactly at the limit -> unchanged
    "y" * (CAP + 1),           # one over -> truncated
    {"command": "z" * (CAP + 500), "count": 3},
    {"nested": {"deep": "w" * (CAP + 10)}, "list": ["a", "b" * (CAP + 1)]},
    {"empty": "", "none": None, "num": 12345},
]


def test_cap_constant_and_behaviour_match_between_hook_and_router():
    assert hook.MAX_FIELD_CHARS == audit_router.MAX_FIELD_CHARS
    for case in CAP_CASES:
        assert hook._cap(case) == audit_router._cap(case)


def test_agent_list_matches_between_hook_and_model():
    # The hook's agent list is the set of keys it knows how to extract.
    assert tuple(hook.FIELD_KEYS) == tuple(AUDIT_AGENTS)


def test_migration_check_constraint_matches_agent_list():
    migration = Path(
        "services/db/migrations/versions/f6a7b8c9d0e1_create_tool_call_events.py"
    ).read_text()
    expected = ", ".join(f"'{agent}'" for agent in AUDIT_AGENTS)
    assert f"agent IN ({expected})" in migration
