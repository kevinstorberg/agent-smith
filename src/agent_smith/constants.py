from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from db.models.agent_smith import HarnessAgent, HarnessHook, HarnessRule, HarnessSkill, HarnessTool

ALL_AGENTS: Final[list[str]] = ["claude", "codex", "gemini"]
ITEM_TYPES: Final[tuple[str, ...]] = ("rule", "skill", "tool", "hook", "agent")
ITEM_MODEL_BY_TYPE: Final[Mapping[str, type[HarnessRule | HarnessSkill | HarnessTool | HarnessHook | HarnessAgent]]] = {
    "rule": HarnessRule,
    "skill": HarnessSkill,
    "tool": HarnessTool,
    "hook": HarnessHook,
    "agent": HarnessAgent,
}
EXPECTED_MIGRATION_HEAD: Final[str] = "7c1f9a2b3d4e"
