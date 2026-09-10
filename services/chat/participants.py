"""Registry of AI chat participants configured via environment variables.

CHAT_MODEL_NAMES and CHAT_MODEL_IDS are parallel, index-aligned,
comma-separated lists: participant N posts as CHAT_MODEL_NAMES[N] using the
model CHAT_MODEL_IDS[N]. The name is the stored message author, the @mention
handle, and the persona name all at once.

Pure env parsing — no HTTP, no database, no graph imports — so the router,
the chat graph, and the chat service can all consume the same registry.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from scripts.shared.agents import AGENT_TARGETS

MAX_PARTICIPANT_NAME_LENGTH = 64

# Identities that AI participants may never claim: the human seat plus the
# real coding-agent sessions that post via the MCP chat_post surface.
RESERVED_CHAT_AUTHORS = frozenset({"user"}) | frozenset(AGENT_TARGETS)


@dataclass(frozen=True)
class ChatParticipant:
    name: str
    model_id: str


def chat_participants() -> list[ChatParticipant]:
    names = _split_env("CHAT_MODEL_NAMES")
    model_ids = _split_env("CHAT_MODEL_IDS")
    if len(names) != len(model_ids):
        raise ValueError(
            "CHAT_MODEL_NAMES and CHAT_MODEL_IDS must be index-aligned lists of "
            f"equal length; got {len(names)} name(s) and {len(model_ids)} model id(s)"
        )

    seen: set[str] = set()
    participants: list[ChatParticipant] = []
    for name, model_id in zip(names, model_ids):
        _validate_name(name)
        folded = name.casefold()
        if folded in seen:
            raise ValueError(f"CHAT_MODEL_NAMES contains duplicate name (case-insensitive): {name!r}")
        seen.add(folded)
        participants.append(ChatParticipant(name=name, model_id=model_id))
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


def _split_env(var: str) -> list[str]:
    raw = os.environ.get(var, "")
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
