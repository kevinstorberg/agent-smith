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
    def __init__(self, source: str | None, *, digest: bool = True, meeting_id: str | None = None) -> None:
        super().__init__(digestion_db.release_owner)
        self.configs = configured_sources(source)
        self.digest = digest
        self.source = source
        self.meeting_id = str(UUID(meeting_id)) if meeting_id is not None else None
        self.transcript_report: dict = {"outcome": "idle"}
        self.memory_report: dict = {"outcome": "idle"}
        self.speaker_report: dict = {"outcome": "idle"}

    async def prepare_manual(self) -> bool:
        if not self.digest or self.meeting_id is not None:
            return False
        self.record = await run_db(digestion_db.claim_manual_memory, list(self.configs), self.owner)
        if self.record:
            self.transcript_report = {"outcome": "ready", "meeting_id": self.record["meeting_id"]}
        return self.record is not None

    async def prepare(self) -> None:
        claim = digestion_db.claim_digestion if self.digest else digestion_db.claim_transcript
        if self.digest:
            self.record = await run_db(digestion_db.claim_identification, self.source, self.owner, self.meeting_id)
        if self.record is None and self.meeting_id is None:
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
        return bool(self.meeting_id is None and self.digest and self.record and self.record["transcript_status"] == "ready"
                    and self.record.get("speaker_status") != "pending" and self.record["memory_status"] == "pending")

    def has_speaker_work(self) -> bool:
        return bool(self.digest and self.record and self.record["transcript_status"] == "ready" and self.record["speaker_status"] == "pending")

    async def identify_participants(self) -> None:
        from services.meetings import speaker_db, speaker_runtime

        if self.has_speaker_work():
            try:
                await speaker_db_guard(self, speaker_runtime.identify)
            except (speaker_db.AttributionInputChanged, speaker_db.PersonaAttributionBusy):
                self.speaker_report.update(outcome="continued")
            self.record = await run_db(digestion_db.get_record, self.record["meeting_id"])

    async def generate_memories(self) -> None:
        if self.has_memory_work():
            await self.run_stage("memory", self.memory_report, self._memory_work, memory_db.record_failure, budget=AGENT_SECONDS)

    async def _memory_work(self, record: dict, *, deadline: float) -> None:
        from services.graphs.model_config import resolve_model_id
        from services.meetings.analysis import analyze_memories
        from services.memory.db import publish
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
        artifact = copy.deepcopy(record["memory_artifact"]) or {
            "version": 1, "offset": 0, "items": [], "published_ids": [],
            "created_at": datetime.now(timezone.utc).isoformat(), "reason": "",
            "model": resolve_model_id("meeting_memory", "curator"), "prompt_version": 3,
        }
        if control.get("active"):
            artifact["manual_request_id"] = control["request_id"]
        if "vocabulary" not in artifact and artifact.get("offset", 0) == 0:
            from services.meetings.vocabulary_db import relevant

            text = "\n".join([record["snapshot"].get("title") or "", record["snapshot"].get("summary_text") or "",
                              *(segment["text"] for segment in record["transcript"]["segments"])])
            artifact["vocabulary"] = await run_db(relevant, text)
        if artifact["version"] != 1:
            raise ValueError("Unsupported meeting memory artifact version")
        if "attribution_snapshot" not in artifact and artifact.get("offset", 0) == 0:
            from services.meetings.speaker_db import context_snapshot
            from services.meetings.participants import meeting_participants
            from services.meetings.profile_db import resolve_participants

            attribution = context_snapshot(record)
            artifact["attribution_snapshot"] = {"transcript_hash": record["transcript_hash"],
                                                "participants_revision": attribution["participants_revision"]}
            raw = meeting_participants(attribution, record["transcript"]["segments"])
            catalog = await run_db(resolve_participants, raw)
            artifact["attribution_identities"] = {
                segment_id: {"display_name": person["display_name"], "email": person.get("email"),
                             "profile_id": person["id"] if "deleted" in person else None,
                             "source": person.get("identity_source")}
                for person in catalog if not person.get("deleted") for segment_id in person["segment_ids"]
            }
        segments = expanded_segments(record["transcript"]["segments"])
        if "attribution_identities" in artifact:
            identities = artifact["attribution_identities"]
            segments = [{**segment, "effective_speaker": identities.get(segment["id"])} for segment in segments]
        artifact["total_units"] = len(segments)
        if artifact["offset"] < len(segments) and "context_labels_revision" not in artifact:
            from services.meetings.labels_db import snapshot as label_snapshot

            label_state = await run_db(label_snapshot, meeting_id)
            artifact["context_labels_revision"] = label_state["labels_revision"]
        await run_db(memory_db.save_progress, meeting_id, self.owner, record["transcript_hash"], artifact)
        snapshot = {**record["snapshot"], **({"vocabulary": artifact["vocabulary"]} if artifact.get("vocabulary") else {})}
        while artifact["offset"] < len(segments):
            window, end = transcript_window(segments, artifact["offset"])
            if control.get("active"):
                await validate_manual_source()
            result = await analyze_memories(snapshot, window, artifact["items"], deadline=deadline,
                **({"validate_context": validate_manual_source} if control.get("active") else {}))
            for atom in result["items"]:
                atom = dict(atom)
                if control.get("active") and any(_same_memory(atom, previous) for previous in artifact["items"]):
                    continue
                atom["id"] = str(uuid5(_MEMORY_NAMESPACE, f"{meeting_id}:{len(artifact['items'])}"))
                artifact["items"].append(atom)
            artifact.update(offset=end, reason=result.get("reason", ""))
            if result.get("context_labels"):
                artifact["context_labels"] = result["context_labels"]
            await run_db(memory_db.save_progress, meeting_id, self.owner, record["transcript_hash"], artifact)
        if artifact.get("context_labels"):
            from services.meetings.labels_db import apply_from_memory

            self.memory_report["labels_outcome"] = await run_db(
                apply_from_memory, meeting_id, self.owner, record["transcript_hash"], record["snapshot"]["revision"],
                artifact["context_labels_revision"], artifact["context_labels"],
            )
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


def _same_memory(left: dict, right: dict) -> bool:
    def identity(item: dict) -> tuple:
        return (" ".join(item["content"].casefold().split()), item.get("kind"),
                sorted((entry["segment_id"], entry["quote"]) for entry in item.get("evidence", [])))
    return identity(left) == identity(right)


async def speaker_db_guard(run: DigestionRun, work) -> None:
    from services.meetings import speaker_db

    async def stage(record: dict, *, deadline: float) -> None:
        try:
            await work(run, record, deadline=deadline)
        except (speaker_db.AttributionInputChanged, speaker_db.PersonaAttributionBusy) as error:
            run.speaker_report.update(outcome="continued", waiting_for="persona_review" if isinstance(error, speaker_db.PersonaAttributionBusy) else "updated_participants")

    await run.run_stage("speaker", run.speaker_report, stage, speaker_db.record_failure, budget=AGENT_SECONDS)
