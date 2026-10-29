from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
from uuid import UUID, uuid5

from services.meetings import digestion_db, memory_db, processing
from services.meetings.digestion import capture_claimed, configured_sources
from services.meetings.service import run_db

JOB_TIMEOUT_SECONDS = processing.JOB_TIMEOUT_SECONDS
GRAPH_WORK_SECONDS = processing.GRAPH_WORK_SECONDS
IMPORT_SECONDS = 60
CAPTURE_SECONDS = 60
AGENT_SECONDS = processing.AGENT_SECONDS
WINDOW_CHARS = processing.WINDOW_CHARS
WINDOW_SEGMENTS = processing.WINDOW_SEGMENTS
_MEMORY_NAMESPACE = UUID("31576a65-6526-5da7-a4c2-c4ef174a665b")


def expanded_segments(segments: list[dict]) -> list[dict]:
    return processing.expanded_segments(segments, max_chars=WINDOW_CHARS)


def transcript_window(segments: list[dict], offset: int) -> tuple[list[dict], int]:
    return processing.transcript_window(segments, offset, max_chars=WINDOW_CHARS, max_segments=WINDOW_SEGMENTS)


def memory_content(snapshot: dict, item: dict) -> str:
    references = ", ".join(evidence["segment_id"] for evidence in item["evidence"])
    return f"{item['content']}\n\nMeeting source: {snapshot['source_url']}\nEvidence: {references}"


class DigestionRun(processing.ProcessingRun):
    def __init__(self, source: str | None, *, digest: bool = True) -> None:
        super().__init__(digestion_db.release_owner)
        self.configs = configured_sources(source)
        self.digest = digest
        self.transcript_report: dict = {"outcome": "idle"}
        self.memory_report: dict = {"outcome": "idle"}

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
        if self.has_memory_work():
            await self.run_stage("memory", self.memory_report, self._memory_work, memory_db.record_failure, budget=AGENT_SECONDS)

    async def _memory_work(self, record: dict, *, deadline: float) -> None:
        from services.graphs.model_config import resolve_model_id
        from services.meetings.analysis import analyze_memories
        from services.memory.db import publish

        meeting_id = record["meeting_id"]
        artifact = copy.deepcopy(record["memory_artifact"]) or {
            "version": 1, "offset": 0, "items": [], "published_ids": [],
            "created_at": datetime.now(timezone.utc).isoformat(), "reason": "",
            "model": resolve_model_id("meeting_memory", "curator"), "prompt_version": 2,
        }
        if not record["memory_artifact"]:
            from services.meetings.vocabulary_db import relevant

            text = "\n".join([record["snapshot"].get("title") or "", record["snapshot"].get("summary_text") or "",
                              *(segment["text"] for segment in record["transcript"]["segments"])])
            artifact["vocabulary"] = await run_db(relevant, text)
        if artifact["version"] != 1:
            raise ValueError("Unsupported meeting memory artifact version")
        segments = expanded_segments(record["transcript"]["segments"])
        artifact["total_units"] = len(segments)
        await run_db(memory_db.save_progress, meeting_id, self.owner, record["transcript_hash"], artifact)
        snapshot = {**record["snapshot"], **({"vocabulary": artifact["vocabulary"]} if artifact.get("vocabulary") else {})}
        while artifact["offset"] < len(segments):
            window, end = transcript_window(segments, artifact["offset"])
            result = await analyze_memories(snapshot, window, artifact["items"], deadline=deadline)
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
            # Older checkpoints must replay their exact publication after a lost receipt.
            tags = item["tags"] if "tags" in item else ["meeting-memory", f"meeting:{meeting_id}", item["kind"]]
            await run_db(publish, item["id"], memory_content(record["snapshot"], item),
                         repo=record["snapshot"].get("project"), tags=tags,
                         created_at=artifact["created_at"], source_type="meeting", source_id=meeting_id)
            artifact["published_ids"].append(item["id"])
            await run_db(memory_db.save_progress, meeting_id, self.owner, record["transcript_hash"], artifact)
        await run_db(memory_db.save_progress, meeting_id, self.owner, record["transcript_hash"], artifact, complete=True)
        record.update(memory_status="done", memory_artifact=artifact)
        self.memory_report.update(outcome="done", memories=len(artifact["items"]), memory_ids=artifact["published_ids"])
