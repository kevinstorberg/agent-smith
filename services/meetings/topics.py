from __future__ import annotations

from typing import Literal, get_args

MemoryKind = Literal["fact", "decision", "commitment", "constraint", "preference", "lesson", "question"]
TOPIC_LIMIT = 8
TOPIC_LENGTH = 50
SUGGESTED_TOPICS = ("product", "security", "paralign", "roadmapping", "growth", "operations")
_ALIASES = {"roadmap": "roadmapping", "roadmaps": "roadmapping", "road-mapping": "roadmapping"}


def normalize_topics(values: list[str], *, allow_empty: bool = True) -> list[str]:
    if not isinstance(values, list) or len(values) > TOPIC_LIMIT:
        raise ValueError(f"Provide at most {TOPIC_LIMIT} topic labels")
    result = []
    for value in values:
        if not isinstance(value, str) or not 1 <= len(value) <= TOPIC_LENGTH:
            raise ValueError(f"Topic labels must be nonblank strings of at most {TOPIC_LENGTH} characters")
        tag = "-".join(value.strip().lower().split())
        tag = _ALIASES.get(tag, tag)
        if not tag or len(tag) > TOPIC_LENGTH or tag == "meeting-memory" or tag.startswith("meeting:"):
            raise ValueError("Use short topic labels, not meeting origin identifiers")
        if tag not in result:
            result.append(tag)
    if not result and not allow_empty:
        raise ValueError("Provide at least one meeting purpose or subject label")
    if result and not set(result).difference(get_args(MemoryKind)):
        raise ValueError("Include a purpose or subject, not only memory classifications")
    return result
