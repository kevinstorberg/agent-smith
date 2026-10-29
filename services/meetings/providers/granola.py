from __future__ import annotations

import asyncio
import json
import random
import re
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

from services.meetings.config import SourceConfig
from services.meetings.types import (
    InvalidCursorError,
    MeetingProviderError,
    MeetingSummary,
    NotePage,
    NoteReference,
    TranscriptPage,
    TranscriptSegment,
)

_API_URL = "https://public-api.granola.ai/v1"
_NOTE_ID = re.compile(r"not_[a-zA-Z0-9]{14}", re.IGNORECASE)
_SCOPE_IDS = {"folder_id": r"fol_[a-zA-Z0-9]{14}", "space_id": r"spa_[a-zA-Z0-9]{14}"}
_REQUEST_BUDGET_SECONDS = 90


class GranolaProvider:
    def __init__(
        self,
        config: SourceConfig,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._params = _list_params(config.provider_options)
        self._api_key = config.api_key
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(15, connect=3), follow_redirects=False,
        )
        self._sleep = sleep
        self._clock = clock
        self._next_request_at = 0.0

    async def list_page(self, cursor: str | None = None) -> NotePage:
        params = dict(self._params)
        if cursor is not None:
            _text(cursor, "cursor", limit=4096, nonempty=True)
            params["cursor"] = cursor
        try:
            response = await self._request("/notes", params=params)
        except MeetingProviderError as error:
            if cursor and error.status_code == 400:
                raise InvalidCursorError("Granola rejected the listing cursor", status_code=400) from None
            raise
        data = _object(response, "listing")
        notes = data.get("notes")
        if not isinstance(notes, list):
            _invalid("notes", "must be an array")
        next_cursor = _next_cursor(data, cursor)
        references = []
        for index, note in enumerate(notes):
            note = _object(note, f"notes[{index}]")
            references.append(NoteReference(
                external_id=_note_id(note.get("id")),
                updated_at=_timestamp(note.get("updated_at"), "updated_at"),
                deleted_at=_optional_timestamp(note.get("deleted_at"), "deleted_at"),
            ))
        return NotePage(notes=tuple(references), next_cursor=next_cursor)

    async def get_summary(self, external_id: str) -> MeetingSummary | None:
        external_id = _note_id(external_id)
        data = await self._request(f"/notes/{external_id}", missing_ok=True)
        if data is None:
            return None
        data = _object(data, "note")
        if _note_id(data.get("id")).lower() != external_id.lower():
            _invalid("id", "does not match the requested note")
        summary = data.get("summary_text")
        if summary is None or summary == "":
            return None
        summary = _text(summary, "summary_text", limit=2_000_000)
        if not summary.strip():
            return None
        source_url = _text(data.get("web_url"), "web_url", limit=4096, nonempty=True)
        parsed_url = urlsplit(source_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc or parsed_url.username or parsed_url.password:
            _invalid("web_url", "must be an HTTPS URL without credentials")
        return MeetingSummary(
            external_id=_note_id(data.get("id")),
            title=_nullable_text(data.get("title"), "title"),
            summary_text=summary,
            summary_markdown=_nullable_text(data.get("summary_markdown"), "summary_markdown", limit=2_000_000),
            source_url=source_url,
            provider_created_at=_timestamp(data.get("created_at"), "created_at"),
            provider_updated_at=_timestamp(data.get("updated_at"), "updated_at"),
            provider_deleted_at=_optional_timestamp(data.get("deleted_at"), "deleted_at"),
            metadata=_metadata(data),
        )

    async def get_transcript_page(self, external_id: str, cursor: str | None = None) -> TranscriptPage:
        external_id = _note_id(external_id)
        params: dict[str, str | int] = {"page_size": 100}
        if cursor is not None:
            params["cursor"] = _text(cursor, "cursor", limit=4096, nonempty=True)
        try:
            response = await self._request(f"/notes/{external_id}/transcript", params=params)
        except MeetingProviderError as error:
            if cursor and error.status_code == 400:
                raise InvalidCursorError("Granola rejected the transcript cursor", status_code=400) from None
            raise
        data = _object(response, "transcript")
        segments = data.get("transcript")
        if not isinstance(segments, list) or len(segments) > 100:
            _invalid("transcript", "must be an array of at most 100 segments")
        next_cursor = _next_cursor(data, cursor)
        return TranscriptPage(tuple(_transcript_segment(segment, index) for index, segment in enumerate(segments)), next_cursor)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self, path: str, *, params: dict | None = None, missing_ok: bool = False,
    ) -> dict | None:
        deadline = self._clock() + _REQUEST_BUDGET_SECONDS
        for attempt in range(4):
            await self._wait(max(0, self._next_request_at - self._clock()), deadline)
            self._next_request_at = self._clock() + 0.25
            response = None
            try:
                async with asyncio.timeout(deadline - self._clock()):
                    response = await self._client.get(
                        f"{_API_URL}{path}", params=params,
                        headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
                        follow_redirects=False,
                    )
            except TimeoutError:
                raise MeetingProviderError("Granola request exceeded its retry budget") from None
            except httpx.TransportError:
                if attempt == 3:
                    raise MeetingProviderError("Granola connection failed after four attempts") from None
            else:
                if response.status_code == 404 and missing_ok:
                    return None
                if response.status_code == 200:
                    try:
                        return _object(response.json(), "response")
                    except ValueError:
                        raise MeetingProviderError("Granola returned invalid JSON") from None
                retryable = response.status_code in {408, 429} or response.status_code >= 500
                if not retryable or attempt == 3:
                    raise MeetingProviderError(
                        f"Granola request failed (HTTP {response.status_code})",
                        status_code=response.status_code,
                    ) from None
            delay = (2 ** attempt) * random.uniform(0.8, 1.2)
            if response is not None:
                delay = max(delay, _retry_after(response.headers.get("Retry-After")))
            await self._wait(delay, deadline)
        raise AssertionError("unreachable")

    async def _wait(self, delay: float, deadline: float) -> None:
        if self._clock() + delay >= deadline:
            raise MeetingProviderError("Granola request exceeded its retry budget")
        if delay > 0:
            await self._sleep(delay)


def _list_params(options: dict) -> dict:
    if set(options) - {"folder_id", "space_id", "page_size"}:
        raise ValueError("Granola provider_options supports only folder_id, space_id, and page_size")
    params = {"page_size": options.get("page_size", 30)}
    if type(params["page_size"]) is not int or not 1 <= params["page_size"] <= 30:
        raise ValueError("Granola page_size must be an integer between 1 and 30")
    for key, pattern in _SCOPE_IDS.items():
        if key in options:
            if not isinstance(options[key], str) or not re.fullmatch(pattern, options[key], re.IGNORECASE):
                raise ValueError(f"Granola {key} has an invalid ID format")
            params[key] = options[key]
    return params


def _invalid(field: str, reason: str) -> None:
    raise MeetingProviderError(f"Granola response field {field}: {reason}") from None


def _next_cursor(data: dict, cursor: str | None) -> str | None:
    if type(data.get("hasMore")) is not bool:
        _invalid("hasMore", "must be a boolean")
    next_cursor = data.get("cursor")
    if next_cursor is not None:
        _text(next_cursor, "cursor", limit=4096, nonempty=True)
    if data["hasMore"] and (not next_cursor or next_cursor == cursor):
        _invalid("cursor", "must advance when hasMore is true")
    return next_cursor if data["hasMore"] else None


def _transcript_segment(value: object, index: int) -> TranscriptSegment:
    field = f"transcript[{index}]"
    data = _object(value, field)
    speaker = data.get("speaker")
    projected = {} if speaker is None else _project(speaker, f"{field}.speaker", ("source", "attribution", "diarization_label", "name"))
    start = _optional_timestamp(data.get("start_time"), f"{field}.start_time")
    end = _optional_timestamp(data.get("end_time"), f"{field}.end_time")
    if start is not None and end is not None and end < start:
        _invalid(f"{field}.end_time", "must not be earlier than start_time")
    segment = TranscriptSegment(_text(data.get("text"), f"{field}.text", limit=2_000_000), projected, start, end)
    try:
        size = len(json.dumps(segment.to_dict(index), ensure_ascii=False).encode("utf-8"))
    except UnicodeError:
        _invalid(field, "must contain valid Unicode")
    if size > 2_000_000:
        _invalid(field, "exceeds 2000000 bytes")
    return segment


def _object(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        _invalid(field, "must be an object")
    return value


def _text(value: object, field: str, *, limit: int = 8192, nonempty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (nonempty and not value.strip()):
        _invalid(field, f"must be {'a nonempty' if nonempty else 'a'} string of at most {limit} characters")
    return value


def _nullable_text(value: object, field: str, *, limit: int = 8192) -> str | None:
    return None if value is None else _text(value, field, limit=limit)


def _note_id(value: object) -> str:
    if not isinstance(value, str) or not _NOTE_ID.fullmatch(value):
        _invalid("id", "must be a valid Granola note ID")
    return value


def _timestamp(value: object, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(_text(value, field).replace("Z", "+00:00"))
    except ValueError:
        _invalid(field, "must be an ISO 8601 timestamp")
    if result.tzinfo is None or result.utcoffset() is None:
        _invalid(field, "must include a timezone")
    return result.astimezone(timezone.utc)


def _optional_timestamp(value: object, field: str) -> datetime | None:
    return None if value is None else _timestamp(value, field)


def _project(data: object, field: str, keys: tuple[str, ...]) -> dict:
    data = _object(data, field)
    return {key: _nullable_text(data[key], f"{field}.{key}") for key in keys if key in data}


def _project_list(data: object, field: str, keys: tuple[str, ...]) -> list[dict]:
    if not isinstance(data, list) or len(data) > 1000:
        _invalid(field, "must be an array of at most 1000 objects")
    return [_project(item, f"{field}[{index}]", keys) for index, item in enumerate(data)]


def _metadata(data: dict) -> dict:
    # A projection prevents private notes and future response fields entering context.
    result = {}
    if data.get("owner") is not None:
        result["owner"] = _project(data["owner"], "owner", ("name", "email"))
    for field, keys in (
        ("attendees", ("name", "email")),
        ("folder_membership", ("id", "name", "parent_folder_id", "space_id")),
        ("space_membership", ("id", "name")),
    ):
        if data.get(field) is not None:
            result[field] = _project_list(data[field], field, keys)
    if data.get("calendar_event") is not None:
        event = _object(data["calendar_event"], "calendar_event")
        projected = _project(event, "calendar_event", ("event_title", "organiser", "calendar_event_id"))
        for field in ("scheduled_start_time", "scheduled_end_time"):
            if field in event:
                stamp = _optional_timestamp(event[field], f"calendar_event.{field}")
                projected[field] = stamp.isoformat() if stamp else None
        if event.get("invitees") is not None:
            projected["invitees"] = _project_list(event["invitees"], "calendar_event.invitees", ("email",))
        result["calendar_event"] = projected
    if len(json.dumps(result).encode("utf-8")) > 65536:
        _invalid("metadata", "exceeds 65536 bytes")
    return result


def _retry_after(value: str | None) -> float:
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0
