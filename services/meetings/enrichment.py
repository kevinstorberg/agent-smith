from __future__ import annotations

import asyncio
import copy
import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid5

from services.meetings import digestion_db, memory_db, memory_pass, processing
from services.meetings.digestion import capture_claimed, configured_sources
from services.meetings.service import run_db
from services.meetings.memory_pass import memory_content as memory_content
from services.observability import trigger_context, work_decision

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


def memory_input(record: dict, artifact: dict) -> tuple[dict, list[dict]]:
    if artifact.get("input_source") != "summary":
        raise memory_pass.SummaryMemoryRetryRequired("Retry memories to start from the saved Granola summary")
    if "input_snapshot" not in artifact:
        artifact["input_snapshot"] = copy.deepcopy(record["snapshot"])
    snapshot = artifact["input_snapshot"]
    if not isinstance(snapshot, dict):
        raise ValueError("Saved memory summary requires a frozen snapshot object")
    text = snapshot.get("summary_text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Summary memory analysis requires a nonblank saved Granola summary")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if artifact.setdefault("input_hash", digest) != digest:
        raise ValueError("Saved memory summary does not match its frozen input hash")
    return {**snapshot, "memory_source": "summary"}, memory_pass.summary_sections(snapshot, max_chars=WINDOW_CHARS)


class DigestionRun(processing.ProcessingRun):
    def __init__(self, source: str | None, *, digest: bool = True) -> None:
        super().__init__(digestion_db.release_owner)
        self.configs = configured_sources(source)
        self.digest = digest
        self.source = source
        self.transcript_report: dict = {"outcome": "idle"}
        self.memory_report: dict = {"outcome": "idle"}

    async def prepare_manual(self) -> bool:
        if not self.digest:
            return False
        self.record = await run_db(digestion_db.claim_manual_memory, list(self.configs), self.owner)
        if self.record:
            self.transcript_report = {"outcome": "ready", "meeting_id": self.record["meeting_id"]}
            with trigger_context(**processing.stage_metadata(self.record, "memory")):
                work_decision("claimed", stage_status=self.record["memory_status"])
        return self.record is not None

    async def prepare(self) -> None:
        claim = digestion_db.claim_digestion if self.digest else digestion_db.claim_transcript
        self.record = await run_db(claim, list(self.configs), self.owner)
        if self.record is None:
            with trigger_context(stage="memory", reason="unknown"):
                work_decision("no_eligible_work", stage_status="idle")
            return
        stage = "transcript_capture" if self.record["transcript_status"] == "pending" else "memory"
        with trigger_context(**processing.stage_metadata(self.record, stage)):
            work_decision("claimed", stage_status=self.record["transcript_status"] if stage == "transcript_capture" else self.record["memory_status"])
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
        return bool(self.digest and self.record and self.record["transcript_status"] == "ready"
                    and self.record["memory_status"] == "pending")

    async def generate_memories(self) -> None:
        if self.has_memory_work():
            await self.run_stage("memory", self.memory_report, self._memory_work, memory_db.record_failure, budget=AGENT_SECONDS)

    async def _memory_work(self, record: dict, *, deadline: float) -> None:
        from services.graphs.model_config import resolve_model_id
        from services.meetings.analysis import analyze_memories
        from services.meetings import manual_stage

        meeting_id = record["meeting_id"]
        control = record.get("manual_analysis", {}).get("memory", {})
        async def validate_manual_source() -> None:
            current = await run_db(manual_stage.before_analysis, meeting_id, self.owner, record["transcript_hash"], "memory")
            if not current or current.get("request_id") != control["request_id"]:
                raise manual_stage.ManualAnalysisInputChanged("Manual memory analysis control was removed or replaced")

        if control.get("active"):
            await validate_manual_source()
            record = {**record, "snapshot": await run_db(digestion_db.get_context, meeting_id)}
        artifact = copy.deepcopy(record["memory_artifact"])
        if not artifact:
            current = await run_db(digestion_db.get_context, meeting_id)
            artifact = memory_pass.restart_artifact(record, current, None, created_at=datetime.now(timezone.utc).isoformat())
            artifact["model"] = resolve_model_id("meeting_memory", "curator")
        if control.get("active"):
            artifact["manual_request_id"] = control["request_id"]
        memory_pass.validate_artifact(artifact, meeting_id)
        if artifact.get("input_source") != "summary":
            if not memory_pass.publication_complete(record, artifact):
                raise memory_pass.SummaryMemoryRetryRequired("Retry memories to start from the saved Granola summary")
            await self._publish_memories(record, artifact, record["snapshot"])
            return
        snapshot, segments = memory_input(record, artifact)
        pass_start = artifact.get("pass_start_index", 0)
        if type(pass_start) is not int or not 0 <= pass_start <= len(artifact["items"]):
            raise ValueError("Memory pass start must identify retained output history")
        if type(artifact.get("offset")) is not int or not 0 <= artifact["offset"] <= len(segments):
            raise ValueError("Memory offset must identify the frozen summary sections")
        if "vocabulary" not in artifact and artifact.get("offset", 0) == 0:
            from services.meetings.vocabulary_db import relevant

            text = "\n".join([snapshot.get("title") or "",
                              *(segment["text"] for segment in segments)])
            artifact["vocabulary"] = await run_db(relevant, text)
        artifact["total_units"] = len(segments)
        if artifact["offset"] < len(segments) and "context_labels_revision" not in artifact:
            from services.meetings.labels_db import snapshot as label_snapshot

            label_state = await run_db(label_snapshot, meeting_id)
            artifact["context_labels_revision"] = label_state["labels_revision"]
        await run_db(memory_db.save_progress, meeting_id, self.owner, record["transcript_hash"], artifact)
        snapshot = {**snapshot, **({"vocabulary": artifact["vocabulary"]} if artifact.get("vocabulary") else {})}
        while artifact["offset"] < len(segments):
            window, end = transcript_window(segments, artifact["offset"])
            if control.get("active"):
                await validate_manual_source()
            previous = [item for item in artifact["items"][pass_start:] if item.get("source") == "summary"]
            with trigger_context(source_kind="summary", source_hash=artifact["input_hash"],
                                 source_revision=snapshot.get("revision"), checkpoint=artifact["offset"]):
                result = await analyze_memories(snapshot, window, previous, deadline=deadline,
                    **({"validate_context": validate_manual_source} if control.get("active") else {}))
            for atom in result["items"]:
                atom = dict(atom)
                atom["source"] = "summary"
                if any(_same_memory(atom, previous) for previous in artifact["items"]):
                    continue
                index = artifact.get("next_item_index", len(artifact["items"]))
                atom["id"] = str(uuid5(_MEMORY_NAMESPACE, f"{meeting_id}:{index}"))
                artifact["next_item_index"] = index + 1
                artifact["items"].append(atom)
            artifact.update(offset=end, reason=result.get("reason", ""))
            if result.get("context_labels"):
                artifact["context_labels"] = result["context_labels"]
            await run_db(memory_db.save_progress, meeting_id, self.owner, record["transcript_hash"], artifact)
        if artifact.get("context_labels"):
            from services.meetings.labels_db import apply_from_memory

            self.memory_report["labels_outcome"] = await run_db(
                apply_from_memory, meeting_id, self.owner, record["transcript_hash"], snapshot["revision"],
                artifact["context_labels_revision"], artifact["context_labels"],
            )
        await self._publish_memories(record, artifact, snapshot)

    async def _publish_memories(self, record: dict, artifact: dict, snapshot: dict) -> None:
        from services.memory.db import publish

        meeting_id = record["meeting_id"]
        memory_pass.freeze_publications(artifact, meeting_id, snapshot)
        await run_db(memory_db.save_progress, meeting_id, self.owner, record["transcript_hash"], artifact)
        for item in artifact["items"]:
            if item["id"] in artifact["published_ids"]:
                continue
            await run_db(memory_db.assert_publishable, meeting_id, self.owner, record["transcript_hash"])
            await run_db(publish, item["id"], **artifact["publication_envelopes"][item["id"]])
            artifact["published_ids"].append(item["id"])
            await run_db(memory_db.save_progress, meeting_id, self.owner, record["transcript_hash"], artifact)
        await run_db(memory_db.save_progress, meeting_id, self.owner, record["transcript_hash"], artifact, complete=True)
        record.update(memory_status="done", memory_artifact=artifact)
        self.memory_report.update(outcome="done", memories=len(artifact["items"]), memory_ids=artifact["published_ids"])


def _same_memory(left: dict, right: dict) -> bool:
    def identity(item: dict) -> tuple:
        return (" ".join(item["content"].casefold().split()), item.get("kind"),
                sorted((entry["segment_id"], entry["quote"]) for entry in item.get("evidence", [])))
    return identity(left) == identity(right)
