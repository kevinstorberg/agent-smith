from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from uuid import UUID

from services.meetings.windows import WINDOW_CHARS
from services.meetings.types import transcript_hash
from services.memory.content import (
    MAX_MEMORY_WORDS,
    memory_word_count,
    normalize_memory_content,
)


class SummaryMemoryRetryRequired(ValueError):
    pass


def publication_units(row: dict, artifact: dict) -> int | None:
    total = artifact.get("total_units")
    if total is not None:
        return total if type(total) is int and total >= 0 else None
    snapshot = row.get("snapshot")
    transcript = row.get("transcript")
    segments = transcript.get("segments") if isinstance(transcript, dict) else None
    if (
        row.get("transcript_status") != "ready"
        or not row.get("captured_at")
        or not isinstance(snapshot, dict)
        or snapshot.get("id") != str(row["meeting_id"])
        or not {"project", "source_url"}.issubset(snapshot)
        or not isinstance(segments, list)
        or not segments
        or any(
            not isinstance(segment, dict) or not isinstance(segment.get("text"), str)
            for segment in segments
        )
        or not row.get("transcript_hash")
        or transcript_hash(segments) != row["transcript_hash"]
    ):
        return None
    return sum(
        max(1, (len(segment["text"]) + WINDOW_CHARS - 1) // WINDOW_CHARS)
        for segment in segments
    )


def publication_complete(row: dict, artifact: dict) -> bool:
    offset, total = artifact.get("offset"), publication_units(row, artifact)
    return type(offset) is int and offset >= 0 and total is not None and offset >= total


def summary_sections(snapshot: dict, *, max_chars: int = WINDOW_CHARS) -> list[dict]:
    if type(max_chars) is not int or max_chars <= 0:
        raise ValueError("Summary section size must be a positive integer")
    text = snapshot.get("summary_text") if isinstance(snapshot, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Memory analysis requires a nonblank saved Granola summary")
    return [
        {"id": f"summary-{index}", "text": text[start : start + max_chars]}
        for index, start in enumerate(range(0, len(text), max_chars))
        if text[start : start + max_chars].strip()
    ]


def memory_content(snapshot: dict, item: dict) -> str:
    references = ", ".join(evidence["segment_id"] for evidence in item["evidence"])
    source = (
        "Granola summary (" + references + ")"
        if item.get("source") == "summary"
        else references
    )
    footer = f"\n\nMeeting source: {snapshot['source_url']}\nEvidence: {source}"
    body_words = MAX_MEMORY_WORDS - memory_word_count(footer)
    if body_words < 1:
        raise ValueError(
            "Memory source and evidence footer leaves no room for content within the word limit"
        )
    return normalize_memory_content(item["content"], max_words=body_words) + footer


def publication_payload(
    meeting_id: str, snapshot: dict, artifact: dict, item: dict
) -> dict:
    if (
        not isinstance(snapshot, dict)
        or "source_url" not in snapshot
        or "project" not in snapshot
    ):
        raise ValueError("Original memory publication context is unavailable")
    return {
        "content": memory_content(snapshot, item),
        "repo": snapshot["project"],
        "tags": copy.deepcopy(
            item.get("tags", ["meeting-memory", f"meeting:{meeting_id}", item["kind"]])
        ),
        "created_at": artifact["created_at"],
        "source_type": "meeting",
        "source_id": meeting_id,
    }


def _timestamp(value) -> None:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.utcoffset() is None:
        raise ValueError("Memory publication requires a timezone-aware created_at")


def validate_artifact(artifact: dict, meeting_id: str) -> None:
    if not isinstance(artifact, dict) or artifact.get("version") != 1:
        raise ValueError("Unsupported meeting memory artifact version")
    if artifact.get("input_source") not in (None, "summary", "transcript"):
        raise ValueError("Unsupported meeting memory input source")
    items, published = artifact.get("items"), artifact.get("published_ids")
    if not isinstance(items, list) or not isinstance(published, list):
        raise ValueError("Memory output and publication receipts must be lists")
    ids = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Retained memory items require UUIDs")
        try:
            UUID(item["id"])
        except ValueError:
            raise ValueError("Retained memory items require UUIDs") from None
        if (
            not isinstance(item.get("content"), str)
            or not item["content"].strip()
            or not isinstance(item.get("kind"), str)
            or not item["kind"].strip()
            or not isinstance(item.get("evidence"), list)
            or any(
                not isinstance(proof, dict)
                or not isinstance(proof.get("segment_id"), str)
                or not isinstance(proof.get("quote"), str)
                for proof in item["evidence"]
            )
            or "tags" in item
            and (
                not isinstance(item["tags"], list)
                or any(not isinstance(tag, str) for tag in item["tags"])
            )
        ):
            raise ValueError(
                "Retained memory items require content, kind, exact evidence and valid tags"
            )
        ids.append(item["id"])
    if (
        len(set(ids)) != len(ids)
        or any(not isinstance(key, str) for key in published)
        or len(set(published)) != len(published)
        or not set(published).issubset(ids)
    ):
        raise ValueError(
            "Memory publication receipts must identify distinct retained items"
        )
    next_index = artifact.get("next_item_index", len(items))
    if type(next_index) is not int or next_index < len(items):
        raise ValueError(
            "Memory item counter must preserve all allocated UUID positions"
        )
    _timestamp(artifact.get("created_at"))
    envelopes = artifact.get("publication_envelopes", {})
    if not isinstance(envelopes, dict) or not set(envelopes).issubset(ids):
        raise ValueError("Memory publication envelopes must identify retained items")
    for envelope in envelopes.values():
        if (
            not isinstance(envelope, dict)
            or set(envelope)
            != {"content", "repo", "tags", "created_at", "source_type", "source_id"}
            or not isinstance(envelope["content"], str)
            or not envelope["content"].strip()
            or envelope["repo"] is not None
            and not isinstance(envelope["repo"], str)
            or not isinstance(envelope["tags"], list)
            or any(not isinstance(tag, str) for tag in envelope["tags"])
            or envelope["source_type"] != "meeting"
            or envelope["source_id"] != meeting_id
        ):
            raise ValueError("Invalid frozen memory publication envelope")
        _timestamp(envelope["created_at"])
    if len(json.dumps(artifact).encode()) > 2_000_000:
        raise ValueError(
            "Meeting stage output must be an object of at most 2000000 bytes"
        )


def freeze_publications(artifact: dict, meeting_id: str, snapshot: dict | None) -> None:
    envelopes = artifact.setdefault("publication_envelopes", {})
    for item in artifact["items"]:
        if item["id"] not in artifact["published_ids"] and item["id"] not in envelopes:
            envelopes[item["id"]] = publication_payload(
                meeting_id, snapshot, artifact, item
            )
    validate_artifact(artifact, meeting_id)


def retained_artifact(row: dict, *, created_at: str) -> dict:
    artifact = copy.deepcopy(
        row.get("memory_artifact")
        or {
            "version": 1,
            "items": [],
            "published_ids": [],
            "created_at": created_at,
        }
    )
    validate_artifact(artifact, str(row["meeting_id"]))
    artifact["next_item_index"] = artifact.get(
        "next_item_index", len(artifact["items"])
    )
    protected = set(artifact["published_ids"]) | set(
        artifact.get("publication_envelopes", {})
    )
    if any(item["id"] not in protected for item in artifact["items"]):
        offset, total = artifact.get("offset"), publication_units(row, artifact)
        if type(offset) is not int or total is None or offset < 0:
            raise ValueError(
                "Original memory publication phase is unknown; uncertain outputs must be preserved"
            )
        if offset < total:
            artifact["items"] = [
                item for item in artifact["items"] if item["id"] in protected
            ]
    return artifact


def restart_artifact(
    row: dict, snapshot: dict, previous_snapshot: dict | None, *, created_at: str
) -> dict:
    sections = summary_sections(snapshot)
    artifact = retained_artifact(row, created_at=created_at)
    meeting_id = str(row["meeting_id"])
    validate_artifact(artifact, meeting_id)
    freeze_publications(artifact, meeting_id, previous_snapshot)
    for key in (
        "vocabulary",
        "attribution_snapshot",
        "attribution_identities",
        "context_labels_revision",
        "context_labels",
        "manual_request_id",
    ):
        artifact.pop(key, None)
    artifact.update(
        offset=0,
        reason="",
        input_source="summary",
        prompt_version=4,
        input_snapshot=copy.deepcopy(snapshot),
        input_hash=hashlib.sha256(snapshot["summary_text"].encode()).hexdigest(),
        total_units=len(sections),
        pass_start_index=len(artifact["items"]),
    )
    validate_artifact(artifact, meeting_id)
    return artifact
