from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TypeVar
from uuid import uuid4

from services.meetings import db
from services.meetings.config import SourceConfig, list_source_names, load_source_config
from services.meetings.factory import build_meeting_provider
from services.meetings.types import InvalidCursorError, MeetingProvider, MeetingProviderError, MeetingSummary

T = TypeVar("T")
log = logging.getLogger(__name__)
_COUNTS = ("listed", "fetched", "processed", "created", "updated", "unchanged", "stale", "pending", "unavailable")


class MeetingSyncError(RuntimeError):
    pass


def _validate_budget(run_budget_seconds: float) -> None:
    if (isinstance(run_budget_seconds, bool) or not isinstance(run_budget_seconds, (int, float))
            or not math.isfinite(run_budget_seconds) or not 0 < run_budget_seconds <= 240):
        raise ValueError("Meeting run budget must be greater than zero and at most 240 seconds")


def _source_failure(source: str, error: Exception) -> dict:
    result = {"source": source, "outcome": "failed", "error_type": type(error).__name__, "counts": None}
    if isinstance(error, MeetingProviderError) and type(error.status_code) is int and 100 <= error.status_code <= 599:
        result["status_code"] = error.status_code
    return result


async def sync_sources(source: str | None = None, *, run_budget_seconds: float = 240) -> dict:
    _validate_budget(run_budget_seconds)
    if source is not None:
        return await sync_source(source, run_budget_seconds=run_budget_seconds)
    # Freeze names, settings and credential values together for this invocation.
    env = dict(os.environ)
    names = list_source_names(env)
    if not names:
        raise ValueError("No meeting connections are configured; set MEETING_SOURCES_JSON")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + run_budget_seconds
    if len(names) > 1:
        last_attempt = {}
        for status in await run_db(db.source_status):
            name = status["source_name"]
            stamp = datetime.fromisoformat(status["updated_at"])
            if name not in last_attempt or stamp > last_attempt[name]:
                last_attempt[name] = stamp
        oldest = datetime.min.replace(tzinfo=timezone.utc)
        names.sort(key=lambda name: (last_attempt.get(name, oldest), name))
    results = []
    for index, name in enumerate(names):
        remaining = deadline - loop.time()
        if remaining <= 0:
            results.append({"source": name, "outcome": "deferred", "counts": None})
            continue
        budget = remaining / (len(names) - index)
        attempt = asyncio.timeout(budget)
        try:
            async with attempt:
                config = load_source_config(name, env)
                result = await sync_source(name, config=config, run_budget_seconds=budget)
        except TimeoutError as error:
            if attempt.expired():
                result = {"source": name, "outcome": "interrupted", "counts": None}
            else:
                result = _source_failure(name, error)
        except Exception as error:
            result = _source_failure(name, error)
        results.append(result)
    outcomes = {result["outcome"] for result in results}
    if "failed" in outcomes:
        outcome = "failed"
    elif outcomes & {"continued", "interrupted", "deferred"}:
        outcome = "continued"
    elif "completed_with_warnings" in outcomes:
        outcome = "completed_with_warnings"
    elif outcomes == {"skipped_busy"}:
        outcome = "skipped_busy"
    else:
        outcome = "completed"
    result = {
        "outcome": outcome,
        "sources": results,
        "counts": {key: sum(item.get(key, 0) for item in results) for key in _COUNTS},
    }
    if outcomes & {"failed", "interrupted", "deferred"}:
        result["known_counts"] = result["counts"]
        result["counts"] = None
    if "failed" in outcomes:
        raise MeetingSyncError(json.dumps(result, sort_keys=True)) from None
    return result


async def run_db(function: Callable[..., T], *args, **kwargs) -> T:
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as cancelled:
        # The SQL thread still owns its transaction after its await is cancelled.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if task.done() and not task.cancelled():
            try:
                task.result()
            except Exception as error:
                cancelled.add_note(f"In-flight meeting DB operation failed: {type(error).__name__}")
        raise cancelled


@dataclass
class SourceClaim:
    owner: str
    state: dict
    outcome: str = "continued"


@asynccontextmanager
async def claimed_source(config: SourceConfig):
    owner = str(uuid4())
    claim = None
    acquiring = True
    primary: BaseException | None = None
    try:
        state = await run_db(db.claim_source, config, owner)
        acquiring = False
        claim = SourceClaim(owner, state) if state is not None else None
        yield claim
    except BaseException as error:
        primary = error
        if claim:
            claim.outcome = "interrupted" if isinstance(error, asyncio.CancelledError) else "failed"
        raise
    finally:
        if claim or acquiring:
            try:
                if claim:
                    outcome = claim.outcome
                else:
                    outcome = "interrupted" if isinstance(primary, asyncio.CancelledError) else "failed"
                await run_db(db.release_source, config, owner, outcome, type(primary).__name__ if primary else None)
            except Exception as error:
                if primary is None:
                    raise
                primary.add_note(f"Meeting claim cleanup failed: {type(error).__name__}")


async def sync_source(
    source: str,
    *,
    provider: MeetingProvider | None = None,
    run_budget_seconds: float = 240,
    config: SourceConfig | None = None,
) -> dict:
    _validate_budget(run_budget_seconds)
    config = load_source_config(source) if config is None else config
    if config.name != source:
        raise ValueError("Meeting source must match its configuration name")
    if provider is None:
        provider = build_meeting_provider(config)
    try:
        async with claimed_source(config) as claim:
            if claim is None:
                return {"source": source, "outcome": "skipped_busy"}
            scan = claim.state["scan"] or _new_scan(claim.state)
            await run_db(db.save_progress, config, claim.owner, scan)
            runner = _SummaryScan(config, claim.owner, scan, provider)
            try:
                async with asyncio.timeout(run_budget_seconds):
                    completed = await runner.run()
            except TimeoutError:
                completed = False
            warnings = scan["counts"]["unavailable"] > 0
            if completed:
                claim.outcome = "completed_with_warnings" if warnings else "completed"
            else:
                claim.outcome = "continued"
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(scan["started_at"])).total_seconds()
            result = {"source": source, "scan_id": scan["id"], "outcome": claim.outcome,
                      "deep": scan["deep"], "degraded": age > 86400, **scan["counts"]}
            log.info("meeting sync source=%s scan=%s outcome=%s listed=%s processed=%s pending=%s",
                     source, scan["id"], claim.outcome, result["listed"], result["processed"], result["pending"])
            return result
    finally:
        await provider.aclose()


def _new_scan(state: dict) -> dict:
    now = datetime.now(timezone.utc)
    last_deep = state["last_deep_completed_at"]
    return {
        "id": str(uuid4()), "started_at": now.isoformat(),
        "deep": last_deep is None or now - last_deep >= timedelta(days=1),
        "phase": "listing", "cursor": None, "page": None, "offset": 0,
        "next_cursor": None, "seen_cursors": [], "restarts": 0, "attempts": 0,
        "counts": dict.fromkeys(_COUNTS, 0),
    }


class _SummaryScan:
    def __init__(self, config: SourceConfig, owner: str, scan: dict, provider: MeetingProvider) -> None:
        self.config = config
        self.owner = owner
        self.scan = scan
        self.provider = provider
        self.counts = scan["counts"]
        self.stored: dict = {}

    async def save(self, **observation) -> dict | None:
        return await run_db(db.save_progress, self.config, self.owner, self.scan, **observation)

    async def run(self) -> bool:
        self.stored = await run_db(db.get_stored_refs, self.config)
        while True:
            page = self.scan["page"]
            if page is not None and self.scan["offset"] < len(page):
                if not await self.process(page[self.scan["offset"]]):
                    return False
            elif page is not None:
                await self.finish_page()
            elif self.scan["phase"] == "listing":
                await self.list_page()
            elif self.scan["phase"] == "missing":
                if not await self.missing_page():
                    await run_db(db.finish_scan, self.config, self.owner, self.scan["deep"], self.scan)
                    return True
            elif self.scan["phase"] == "done":
                await run_db(db.finish_scan, self.config, self.owner, self.scan["deep"], self.scan)
                return True
            else:
                raise ValueError("Meeting checkpoint has an invalid scan phase")

    async def list_page(self) -> None:
        cursor = self.scan["cursor"]
        try:
            page = await self.provider.list_page(cursor)
        except InvalidCursorError:
            if self.scan["restarts"] >= 1:
                raise MeetingProviderError("Meeting listing cursor repeatedly expired; narrow the source scope") from None
            self.scan.update(cursor=None, seen_cursors=[], restarts=self.scan["restarts"] + 1)
            await self.save()
            return
        seen = self.scan["seen_cursors"]
        if cursor is not None:
            seen.append(cursor)
        if page.next_cursor is not None and (page.next_cursor in seen or len(seen) >= 10000):
            raise MeetingProviderError("Meeting listing cursor did not progress; inspect source pagination")
        self.scan.update(
            page=[{"id": note.external_id, "updated_at": note.updated_at.isoformat(),
                   "deleted_at": note.deleted_at.isoformat() if note.deleted_at else None} for note in page.notes],
            offset=0, next_cursor=page.next_cursor,
        )
        self.counts["listed"] += len(page.notes)
        await self.save()

    async def finish_page(self) -> None:
        if self.scan["phase"] == "listing":
            self.scan["cursor"] = self.scan["next_cursor"]
            if self.scan["cursor"] is None:
                self.scan["phase"] = "missing" if self.scan["deep"] else "done"
        self.scan.update(page=None, offset=0, attempts=0)
        await self.save()

    async def missing_page(self) -> bool:
        # Recheck records omitted by LIST; absence alone does not establish deletion.
        self.stored = await run_db(db.get_stored_refs, self.config)
        missing = [key for key, row in self.stored.items() if row["last_seen_scan_id"] != self.scan["id"]]
        if not missing:
            return False
        self.scan.update(page=[{"id": key, "updated_at": None, "deleted_at": None} for key in sorted(missing)[:30]], offset=0)
        await self.save()
        return True

    async def process(self, reference: dict) -> bool:
        external_id = reference["id"]
        old = self.stored.get(external_id)
        updated_at = datetime.fromisoformat(reference["updated_at"]) if reference["updated_at"] else None
        deleted_at = datetime.fromisoformat(reference["deleted_at"]) if reference["deleted_at"] else None
        if deleted_at is not None:
            self.advance()
            if old and old["provider_updated_at"] > updated_at:
                self.counts["stale"] += 1
                await self.save(seen_id=external_id)
            else:
                self.counts["unavailable"] += 1
                await self.save(unavailable_id=external_id, deleted_at=deleted_at, observed_updated_at=updated_at)
            return True
        if (not self.scan["deep"] and old and old["available"] and old["missing_count"] == 0
                and updated_at is not None and old["provider_updated_at"] >= updated_at):
            self.counts["unchanged"] += 1
            self.advance()
            await self.save(seen_id=external_id)
            return True
        summary = await self.read_detail(external_id, updated_at)
        if summary is None:
            self.scan["attempts"] += 1
            resolved = self.scan["attempts"] >= 3
            self.counts["pending"] = 0 if resolved else 1
            if resolved:
                self.counts["unavailable"] += 1
                self.advance()
            await self.save(unavailable_id=external_id)
            return resolved
        self.advance()
        result = await self.save(summary=summary)
        self.counts[result["status"]] += 1
        self.stored[external_id] = {
            "provider_updated_at": max(summary.provider_updated_at, old["provider_updated_at"]) if old else summary.provider_updated_at,
            "available": summary.provider_deleted_at is None, "missing_count": 0,
            "last_seen_scan_id": self.scan["id"],
        }
        return True

    async def read_detail(self, external_id: str, listed_version: datetime | None) -> MeetingSummary | None:
        for attempt in range(3):
            summary = await self.provider.get_summary(external_id)
            self.counts["fetched"] += 1
            if summary is None:
                return None
            if not isinstance(summary, MeetingSummary) or summary.external_id != external_id:
                raise MeetingProviderError("Meeting provider returned a different note identity")
            if listed_version is None or summary.provider_updated_at >= listed_version:
                return summary
            if attempt < 2:
                await asyncio.sleep(0.25)
        raise MeetingProviderError("Meeting detail is older than its listing version; retry on the next interval")

    def advance(self) -> None:
        self.scan["offset"] += 1
        self.scan["attempts"] = 0
        self.counts["pending"] = 0
        self.counts["processed"] += 1
