from __future__ import annotations

import asyncio
import json
import math
import os
from contextlib import asynccontextmanager
from uuid import uuid4

from services.meetings import digestion_db as db
from services.meetings.config import list_source_names, load_source_config
from services.meetings.factory import build_meeting_provider
from services.meetings.service import run_db
from services.meetings.types import InvalidCursorError, MeetingProviderError, TranscriptPage

MAX_TRANSCRIPT_BYTES = 20_000_000
MAX_TRANSCRIPT_SEGMENTS = 100_000
MAX_TRANSCRIPT_PAGES = 2000
PROVIDER_CLOSE_SECONDS = 5


class TranscriptChangedError(MeetingProviderError):
    pass


class TranscriptLimitError(MeetingProviderError):
    pass


@asynccontextmanager
async def claimed_meeting(identities: list[tuple[str, str]]):
    owner = str(uuid4())
    primary = None
    try:
        row = await run_db(db.claim_transcript, identities, owner)
        yield (owner, row)
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            # Acquisition can commit before a cancelled await returns its row.
            await run_db(db.release_owner, owner)
        except Exception as error:
            if primary is None:
                raise
            primary.add_note(f"Meeting digestion cleanup failed: {type(error).__name__}")


async def capture_transcripts(source: str | None = None, *, run_budget_seconds: float = 120) -> dict:
    if type(run_budget_seconds) not in (int, float) or not math.isfinite(run_budget_seconds) or not 0 < run_budget_seconds <= 480:
        raise ValueError("Transcript budget must be a finite number greater than zero and at most 480 seconds")
    report = {"outcome": "continued"}
    deadline = asyncio.timeout(run_budget_seconds)
    try:
        async with deadline:
            await _capture_next(source, report)
    except TimeoutError:
        report.update(outcome="continued" if deadline.expired() else "failed", error_type="TimeoutError")
    except Exception as error:
        report.update(outcome="failed", error_type=type(error).__name__)
    return report


def configured_sources(source: str | None, env: dict | None = None) -> dict:
    env = dict(os.environ) if env is None else env
    names = [source] if source is not None else list_source_names(env)
    configs = {}
    for name in names:
        try:
            config = load_source_config(name, env)
        except ValueError:
            continue  # The import reports invalid credentials/settings; healthy sources can progress.
        configs[(config.provider, config.account_key)] = config
    return configs


async def _capture_next(source: str | None, report: dict) -> None:
    configs = configured_sources(source)
    async with claimed_meeting(list(configs)) as (owner, row):
        if row is None:
            report["outcome"] = "idle"
            return
        await capture_claimed(configs, owner, row, report)


async def capture_claimed(configs: dict, owner: str, row: dict, report: dict) -> None:
    meeting_id = row["meeting_id"]
    report["meeting_id"] = meeting_id
    context = await run_db(db.get_context, meeting_id)
    if context is None:
        await run_db(db.record_failure, meeting_id, owner, "SourceUnavailable", status="unavailable")
        report["outcome"] = "unavailable"
        return
    provider = None
    try:
        config = configs[(context["provider"], context["account_key"])]
        provider = build_meeting_provider(config)
        reader = getattr(provider, "get_transcript_page", None)
        if reader is None:
            await run_db(db.record_failure, meeting_id, owner, "TranscriptUnsupported", status="unsupported")
            report["outcome"] = "unsupported"
            return
        segments = await _capture(provider, context, row, owner)
        report.update(outcome="ready", segments=segments)
    except TranscriptChangedError:
        await run_db(db.reset_capture, meeting_id, owner)
        report.update(outcome="continued", error_type="TranscriptChangedError")
    except Exception as error:
        status = "unavailable" if isinstance(error, MeetingProviderError) and error.status_code in {403, 404} else None
        await run_db(db.record_failure, meeting_id, owner, type(error).__name__, status=status)
        report.update(outcome="failed", error_type=type(error).__name__)
    finally:
        if provider is not None:
            async with asyncio.timeout(PROVIDER_CLOSE_SECONDS):
                await provider.aclose()

async def _capture(provider, context: dict, row: dict, owner: str) -> int:
    meeting_id = context["id"]
    version = context["provider_updated_at"]
    await _check_version(provider, context)
    saved = row["transcript"]
    if (row["snapshot"].get("provider_updated_at") != version
            or row["snapshot"].get("revision") != context["revision"]):
        saved = {}
    segments = list(saved.get("segments", []))
    cursor = saved.get("cursor")
    seen = list(saved.get("seen_cursors", []))
    restarts = 0
    while True:
        try:
            page = await provider.get_transcript_page(context["external_id"], cursor)
        except InvalidCursorError:
            if restarts:
                raise MeetingProviderError("Transcript cursor repeatedly expired") from None
            restarts += 1
            cursor, seen, segments = None, [], []
            await run_db(db.reset_capture, meeting_id, owner)
            continue
        if not isinstance(page, TranscriptPage):
            raise MeetingProviderError("Meeting provider returned an invalid transcript page")
        if cursor is not None:
            seen.append(cursor)
        if page.next_cursor and (page.next_cursor == cursor or page.next_cursor in seen):
            raise MeetingProviderError("Transcript cursor did not advance")
        start = len(segments)
        segments.extend(segment.to_dict(start + index) for index, segment in enumerate(page.segments))
        capture = {"segments": segments, "cursor": page.next_cursor, "seen_cursors": seen}
        if (len(segments) > MAX_TRANSCRIPT_SEGMENTS or len(seen) >= MAX_TRANSCRIPT_PAGES
                or len(json.dumps(capture).encode()) > MAX_TRANSCRIPT_BYTES):
            raise TranscriptLimitError("Transcript exceeds supported capture limits")
        if page.next_cursor is None:
            await _check_version(provider, context)
            if not segments:
                raise MeetingProviderError("Meeting transcript is empty")
            await run_db(db.save_capture, meeting_id, owner, context, capture, complete=True)
            return len(segments)
        await run_db(db.save_capture, meeting_id, owner, context, capture)
        cursor = page.next_cursor


async def _check_version(provider, context: dict) -> None:
    summary = await provider.get_summary(context["external_id"])
    if summary is None or summary.provider_deleted_at is not None:
        raise MeetingProviderError("Meeting is no longer available", status_code=404)
    if summary.external_id != context["external_id"] or summary.provider_updated_at.isoformat() != context["provider_updated_at"]:
        raise TranscriptChangedError("Meeting changed during transcript capture; retry after synchronization")
