from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class MeetingProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class InvalidCursorError(MeetingProviderError):
    pass


@dataclass(frozen=True)
class NoteReference:
    external_id: str
    updated_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class NotePage:
    notes: tuple[NoteReference, ...]
    next_cursor: str | None = None


@dataclass(frozen=True)
class TranscriptSegment:
    text: str
    speaker: dict[str, str | None]
    start_time: datetime | None = None
    end_time: datetime | None = None

    def to_dict(self, index: int) -> dict:
        if type(index) is not int or index < 0:
            raise ValueError("Transcript segment index must be a nonnegative integer")
        return {
            "id": f"segment-{index}", "text": self.text, "speaker": dict(self.speaker),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
        }


@dataclass(frozen=True)
class TranscriptPage:
    segments: tuple[TranscriptSegment, ...]
    next_cursor: str | None = None


@dataclass(frozen=True)
class MeetingSummary:
    external_id: str
    title: str | None
    summary_text: str
    summary_markdown: str | None
    source_url: str
    provider_created_at: datetime
    provider_updated_at: datetime
    provider_deleted_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def payload_hash(self, project: str | None = None) -> str:
        payload = {
            "title": self.title,
            "summary_text": self.summary_text,
            "summary_markdown": self.summary_markdown,
            "source_url": self.source_url,
            "metadata": _canonical_metadata(self.metadata),
            "project": project,
            "deleted_at": self.provider_deleted_at.isoformat() if self.provider_deleted_at else None,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()


def _canonical_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    result = dict(metadata)
    groups = [(result, key) for key in ("attendees", "folder_membership", "space_membership")]
    if isinstance(result.get("calendar_event"), dict):
        result["calendar_event"] = dict(result["calendar_event"])
        groups.append((result["calendar_event"], "invitees"))
    for container, key in groups:
        if isinstance(container.get(key), list):
            container[key] = sorted(container[key], key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return result


class MeetingProvider(Protocol):
    async def list_page(self, cursor: str | None = None, *, updated_after: datetime | None = None) -> NotePage: ...

    async def get_summary(self, external_id: str) -> MeetingSummary | None: ...

    async def get_transcript_page(self, external_id: str, cursor: str | None = None) -> TranscriptPage: ...

    async def aclose(self) -> None: ...
