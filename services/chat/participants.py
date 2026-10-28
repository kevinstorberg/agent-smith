"""Registry of AI chat participants configured via environment variables.

CHAT_MODEL_NAMES lists the participants. Each name is the stored message
author, the @mention handle, and the persona name all at once. Each
participant is the graph model role chat_<name>, so Kimi reads CHAT_KIMI_MODEL_* settings
(usually just CHAT_KIMI_MODEL_PRESET), then its preset, then the shared
CHAT_MODEL_* settings, then GRAPH_MODEL_*.

Pure env parsing — no HTTP, no database, no graph runtime imports — so the
router, the chat graph, and the chat service can all consume the same registry.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from scripts.shared.agents import AGENT_TARGETS
from scripts.shared.env import env_prefix
from services.graphs.model_config import resolve_model_id

MAX_PARTICIPANT_NAME_LENGTH = 64
CHAT_MODEL_ROLE = "chat"

# Identities that AI participants may never claim: the human seat plus the
# real coding-agent sessions that post via the MCP chat_post surface.
RESERVED_CHAT_AUTHORS = frozenset({"user"}) | frozenset(AGENT_TARGETS)


@dataclass(frozen=True)
class ChatParticipant:
    name: str
    model_role: str


def chat_participants(env: Mapping[str, str] | None = None) -> list[ChatParticipant]:
    env = os.environ if env is None else env
    if "CHAT_MODEL_IDS" in env:
        raise ValueError(
            "CHAT_MODEL_IDS is obsolete: give each participant its own model with "
            "CHAT_<NAME>_MODEL_PRESET, e.g. CHAT_KIMI_MODEL_PRESET=KIMI_K3. "
            "See the chat settings in .env.default."
        )

    seen: set[str] = set()
    names_by_prefix: dict[str, str] = {}
    participants: list[ChatParticipant] = []
    for name in _split_env(env, "CHAT_MODEL_NAMES"):
        _validate_name(name)
        folded = name.casefold()
        if folded in seen:
            raise ValueError(f"CHAT_MODEL_NAMES contains duplicate name (case-insensitive): {name!r}")
        seen.add(folded)

        prefix = env_prefix(f"{CHAT_MODEL_ROLE}_{name}")
        if prefix == env_prefix(CHAT_MODEL_ROLE):
            raise ValueError(f"chat participant name {name!r} needs letters or digits")
        if prefix in names_by_prefix:
            raise ValueError(
                f"chat participants {names_by_prefix[prefix]!r} and {name!r} would both read "
                f"{prefix}_MODEL_* settings; rename one"
            )
        names_by_prefix[prefix] = name

        model_role = prefix.lower()
        resolve_model_id(model_role, CHAT_MODEL_ROLE, env=env)
        participants.append(ChatParticipant(name=name, model_role=model_role))
    return participants


def find_participant(name: str) -> ChatParticipant:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("participant must be a non-empty string")
    folded = name.strip().casefold()
    participants = chat_participants()
    for participant in participants:
        if participant.name.casefold() == folded:
            return participant
    valid = ", ".join(p.name for p in participants)
    raise ValueError(f"unknown chat participant {name!r}; valid participants: {valid}")


def _split_env(env: Mapping[str, str], var: str) -> list[str]:
    raw = env.get(var, "")
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError(f"{var} must be a non-empty comma-separated list; got {raw!r}")
    return values


def _validate_name(name: str) -> None:
    if len(name) > MAX_PARTICIPANT_NAME_LENGTH:
        raise ValueError(
            f"chat participant name must be {MAX_PARTICIPANT_NAME_LENGTH} characters "
            f"or fewer; got {name!r}"
        )
    if name.casefold() in RESERVED_CHAT_AUTHORS:
        raise ValueError(
            f"chat participant name {name!r} collides with a reserved identity "
            f"({', '.join(sorted(RESERVED_CHAT_AUTHORS))}); pick a distinct name"
        )
