from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
from uuid import UUID, uuid4, uuid5

from services.meetings import digestion_db, memory_db
from services.meetings.digestion import capture_claimed, configured_sources
from services.meetings.service import run_db

JOB_TIMEOUT_SECONDS = 600
GRAPH_WORK_SECONDS = 540
IMPORT_SECONDS = 60
CAPTURE_SECONDS = 60
AGENT_SECONDS = 150
WINDOW_CHARS = 24_000
WINDOW_SEGMENTS = 100
_MEMORY_NAMESPACE = UUID("31576a65-6526-5da7-a4c2-c4ef174a665b")


def expanded_segments(segments: list[dict]) -> list[dict]:
    return [
        {**segment, "text": segment["text"][start:start + WINDOW_CHARS]}
        for segment in segments
        for start in range(0, max(1, len(segment["text"])), WINDOW_CHARS)
    ]


def transcript_window(segments: list[dict], offset: int) -> tuple[list[dict], int]:
    window, size, seen = [], 0, set()
    for segment in segments[offset:]:
        length = len(segment["text"])
        # Split pieces retain their canonical evidence ID. Separate windows
        # keep each agent's segment-ID lookup unambiguous.
        if len(window) >= WINDOW_SEGMENTS or segment["id"] in seen or (window and size + length > WINDOW_CHARS):
            break
        if length > WINDOW_CHARS:
            raise ValueError("A transcript segment exceeds the supported agent window")
        window.append(segment)
        size += length
        seen.add(segment["id"])
    return window, offset + len(window)


def memory_content(snapshot: dict, item: dict) -> str:
    references = ", ".join(evidence["segment_id"] for evidence in item["evidence"])
    return f"{item['content']}\n\nMeeting source: {snapshot['source_url']}\nEvidence: {references}"


class DigestionRun:
    def __init__(self, source: str | None, *, digest: bool = True) -> None:
        self.configs = configured_sources(source)
        self.owner = str(uuid4())
        self.digest = digest
        self.record: dict | None = None
        self.transcript_report: dict = {"outcome": "idle"}
        self.memory_report: dict = {"outcome": "idle"}
        self.deadline = 0.0

    async def __aenter__(self):
        self.deadline = asyncio.get_running_loop().time() + GRAPH_WORK_SECONDS
        return self

    async def __aexit__(self, error_type, error, traceback):
        try:
            # The scope spans graph edges as well as node bodies.
            await run_db(digestion_db.release_owner, self.owner)
        except Exception as cleanup:
            if error is None:
                raise
            error.add_note(f"Digestion release failed: {type(cleanup).__name__}")

    @property
    def remaining(self) -> float:
        return max(0, self.deadline - asyncio.get_running_loop().time())

    async def prepare(self) -> None:
        claim = digestion_db.claim_digestion if self.digest else digestion_db.claim_transcript
        self.record = await run_db(claim, list(self.configs), self.owner)
        if self.record is None:
            return
        meeting_id = self.record["meeting_id"]
        self.transcript_report = {"outcome": "ready", "meeting_id": meeting_id}
        if self.record["transcript_status"] == "pending":
            attempt = asyncio.timeout(min(CAPTURE_SECONDS, self.remaining))
            try:
                async with attempt:
                    await capture_claimed(self.configs, self.owner, self.record, self.transcript_report)
            except TimeoutError:
                self.transcript_report.update(outcome="continued" if attempt.expired() else "failed", error_type="TimeoutError")
            except Exception as error:
                self.transcript_report.update(outcome="failed", error_type=type(error).__name__)
        self.record = await run_db(digestion_db.get_record, meeting_id)

    def has_memory_work(self) -> bool:
        return bool(self.digest and self.record and self.record["transcript_status"] == "ready" and self.record["memory_status"] == "pending")

    async def generate_memories(self) -> None:
        if not self.has_memory_work():
            return
        record = self.record
        meeting_id = record["meeting_id"]
        self.memory_report = {"outcome": "continued", "meeting_id": meeting_id}
        if self.remaining < 50:
            return
        attempt = asyncio.timeout(min(AGENT_SECONDS, self.remaining - 10))
        try:
            async with attempt:
                await self._memory_work(record)
        except TimeoutError:
            if not attempt.expired():
                await self._memory_failure("TimeoutError")
        except Exception as error:
            await self._memory_failure(type(error).__name__)

    async def _memory_failure(self, error_type: str) -> None:
        await run_db(memory_db.record_failure, self.record["meeting_id"], self.owner, error_type)
        self.memory_report.update(outcome="failed", error_type=error_type)

    async def _memory_work(self, record: dict) -> None:
        from services.graphs.model_config import resolve_model_id
        from services.meetings.analysis import analyze_memories
        from services.memory.db import publish

        meeting_id = record["meeting_id"]
        artifact = copy.deepcopy(record["memory_artifact"]) or {
            "version": 1, "offset": 0, "items": [], "published_ids": [],
            "created_at": datetime.now(timezone.utc).isoformat(), "reason": "",
            "model": resolve_model_id("meeting_memory", "curator"), "prompt_version": 1,
        }
        if artifact["version"] != 1:
            raise ValueError("Unsupported meeting memory artifact version")
        segments = expanded_segments(record["transcript"]["segments"])
        while artifact["offset"] < len(segments):
            window, end = transcript_window(segments, artifact["offset"])
            result = await analyze_memories(record["snapshot"], window, artifact["items"], deadline=self.deadline)
            for atom in result["items"]:
                atom = dict(atom)
                atom["id"] = str(uuid5(_MEMORY_NAMESPACE, f"{meeting_id}:{len(artifact['items'])}"))
                artifact["items"].append(atom)
            artifact.update(offset=end, reason=result.get("reason", ""))
            await run_db(memory_db.save_progress, meeting_id, self.owner, record["transcript_hash"], artifact)
        for item in artifact["items"]:
            if item["id"] in artifact["published_ids"]:
                continue
            await run_db(memory_db.assert_publishable, meeting_id, self.owner, record["transcript_hash"])
            await run_db(publish, item["id"], memory_content(record["snapshot"], item),
                         repo=record["snapshot"].get("project"), tags=["meeting-memory", f"meeting:{meeting_id}", item["kind"]],
                         created_at=artifact["created_at"])
            artifact["published_ids"].append(item["id"])
            await run_db(memory_db.save_progress, meeting_id, self.owner, record["transcript_hash"], artifact)
        await run_db(memory_db.save_progress, meeting_id, self.owner, record["transcript_hash"], artifact, complete=True)
        record.update(memory_status="done", memory_artifact=artifact)
        self.memory_report.update(outcome="done", memories=len(artifact["items"]), memory_ids=artifact["published_ids"])
