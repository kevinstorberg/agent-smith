from __future__ import annotations

import asyncio
import re
from uuid import uuid4

from services.meetings import digestion_db, stage_db
from services.meetings.db import ClaimLostError
from services.meetings.service import run_db
from services.meetings.windows import WINDOW_CHARS, WINDOW_SEGMENTS

JOB_TIMEOUT_SECONDS = 600
GRAPH_WORK_SECONDS = 540
AGENT_SECONDS = 150


def expanded_segments(segments: list[dict], *, max_chars: int = WINDOW_CHARS) -> list[dict]:
    return [{**segment, "text": segment["text"][start:start + max_chars]}
            for segment in segments for start in range(0, max(1, len(segment["text"])), max_chars)]


def transcript_window(segments: list[dict], offset: int, *, max_chars: int = WINDOW_CHARS,
                      max_segments: int = WINDOW_SEGMENTS) -> tuple[list[dict], int]:
    window, size, seen = [], 0, set()
    for segment in segments[offset:]:
        length = len(segment["text"])
        # Split pieces retain their source evidence IDs; keep each window unambiguous.
        if len(window) >= max_segments or segment["id"] in seen or (window and size + length > max_chars):
            break
        if length > max_chars:
            raise ValueError("A transcript segment exceeds the supported agent window")
        window.append(segment)
        size += length
        seen.add(segment["id"])
    return window, offset + len(window)


def failure_category(error: Exception) -> str:
    category = getattr(error, "error_type", None)
    return category if isinstance(category, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,99}", category) else type(error).__name__


def graph_outcome(result: dict, stages: list[dict]) -> dict:
    outcomes = [result.get("outcome"), *(stage.get("outcome") for stage in stages)]
    outcome = "failed" if "failed" in outcomes else "continued" if "continued" in outcomes else result.get("outcome", "completed")
    return {**result, "outcome": outcome}


def _terminal_report(latest: dict | None, stage: str, request_id: str | None, before: dict, report: dict) -> bool:
    if latest is None:
        return False
    current_request = latest.get("manual_analysis", {}).get(stage, {}).get("request_id")
    if request_id and current_request != request_id:
        report.update(outcome="failed", error_type="ManualAnalysisSuperseded", progress=before)
        return True
    status = latest.get(stage + "_status")
    if status not in {"done", "failed"}:
        return False
    report.update(outcome=status, progress=stage_db.progress(latest, stage))
    if status == "failed":
        report["error_type"] = latest.get(stage + "_error") or report.get("error_type") or "StageFailed"
    else:
        report.pop("error_type", None)
    return True


class ProcessingRun:
    def __init__(self, release_owner, *, get_record=digestion_db.get_record) -> None:
        self.owner = str(uuid4())
        self.record: dict | None = None
        self.deadline = 0.0
        self._release_owner = release_owner
        self._get_record = get_record

    async def __aenter__(self):
        self.deadline = asyncio.get_running_loop().time() + GRAPH_WORK_SECONDS
        return self

    async def __aexit__(self, error_type, error, traceback):
        try:
            await run_db(self._release_owner, self.owner)
        except Exception as cleanup:
            if error is None:
                raise
            error.add_note(f"Processing release failed: {type(cleanup).__name__}")

    @property
    def remaining(self) -> float:
        return max(0, self.deadline - asyncio.get_running_loop().time())

    async def run_stage(self, stage: str, report: dict, work, record_failure, *, budget: float = AGENT_SECONDS) -> None:
        from services.meetings.analysis import AnalysisBudgetExpired

        record = self.record
        context_id = record.get("context_id") or record["meeting_id"]
        report.update(outcome="continued")
        if "context_id" in record:
            report["context_id"] = context_id
        if "meeting_id" in record:
            report["meeting_id"] = record["meeting_id"]
        before = stage_db.progress(record, stage)
        request_id = record.get("manual_analysis", {}).get(stage, {}).get("request_id")
        if self.remaining < 50:
            report["progress"] = before
            return
        deadline = asyncio.get_running_loop().time() + min(budget, self.remaining - 10)
        attempt = asyncio.timeout_at(deadline)
        try:
            async with attempt:
                await work(record, deadline=deadline)
        except Exception as error:
            expired = isinstance(error, AnalysisBudgetExpired) or (isinstance(error, TimeoutError) and attempt.expired())
            if expired:
                latest = await run_db(self._get_record, context_id)
                if _terminal_report(latest, stage, request_id, before, report):
                    return
                after = stage_db.progress(latest, stage)
                if after["processed_units"] > before["processed_units"] or after["saved_count"] > before["saved_count"]:
                    report["progress"] = after
                    return
            category = "StageNoProgressTimeout" if expired else failure_category(error)
            try:
                await run_db(record_failure, context_id, self.owner, category)
            except ClaimLostError:
                latest = await run_db(self._get_record, context_id)
                if request_id and _terminal_report(latest, stage, request_id, before, report):
                    return
                raise
            report.update(outcome="failed", error_type=category)
        latest = await run_db(self._get_record, context_id)
        if not _terminal_report(latest, stage, request_id, before, report):
            report["progress"] = stage_db.progress(latest, stage)
