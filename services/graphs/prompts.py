"""Prompt fragments shared across graph personas."""
from __future__ import annotations


def grounding_block(source_description: str) -> str:
    """The anti-hallucination grounding contract for reasoning-only graph agents.

    ``source_description`` names the only material the agent may reason from,
    e.g. "The proposal text in this message" (opinion graph) or "The room
    topic, context, and transcript in this message" (chat graph).
    """
    assert source_description.strip(), "source_description must be non-empty"
    return (
        "GROUNDING (critical): You have NO access to any codebase, filesystem, "
        f"runtime, or tools. {source_description} is your ONLY source of "
        "information. Never invent specifics that are not present in it — do "
        "not name classes, functions, files, database engines, libraries, or "
        "infrastructure it does not mention, and never claim to have inspected "
        "a codebase or filesystem. If a detail is not stated, treat it as an "
        "unstated assumption to flag (phrased conditionally, e.g. 'if X uses "
        "Y...'), never as established fact."
    )
