from __future__ import annotations

import asyncio
import copy
import hashlib
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
    if item.get("source") == "summary":
        return f"{item['content']}\n\nMeeting source: {snapshot['source_url']}\nEvidence: Granola summary ({references})"
    return f"{item['content']}\n\nMeeting source: {snapshot['source_url']}\nEvidence: {references}"


def memory_input(record: dict, artifact: dict) -> tuple[dict, list[dict]]:
    source = artifact.get("input_source", "transcript")
    if not isinstance(source, str) or source not in {"summary", "transcript"}:
        raise ValueError("Unsupported meeting memory input source")
    if source == "transcript":
        return record["snapshot"], expanded_segments(record["transcript"]["segments"])
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
    sections = expanded_segments([{"id": "summary", "text": text}])
    return {**snapshot, "memory_source": "summary"}, [
        {**section, "id": f"summary-{index}"} for index, section in enumerate(sections)
        if section["text"].strip()
    ]


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
        return self.record is not None

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
        return bool(self.digest and self.record and self.record["transcript_status"] == "ready"
                    and self.record["memory_status"] == "pending")

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
            "model": resolve_model_id("meeting_memory", "curator"), "prompt_version": 4,
            "input_source": "summary",
        }
        if control.get("active"):
            artifact["manual_request_id"] = control["request_id"]
        if artifact["version"] != 1:
            raise ValueError("Unsupported meeting memory artifact version")
        snapshot, segments = memory_input(record, artifact)
        input_source = artifact.get("input_source", "transcript")
        if "vocabulary" not in artifact and artifact.get("offset", 0) == 0:
            from services.meetings.vocabulary_db import relevant

            context_summary = (snapshot.get("summary_text") or "") if input_source == "transcript" else ""
            text = "\n".join([snapshot.get("title") or "", context_summary,
                              *(segment["text"] for segment in segments)])
            artifact["vocabulary"] = await run_db(relevant, text)
        if input_source == "transcript" and "attribution_snapshot" not in artifact and artifact.get("offset", 0) == 0:
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
        if input_source == "transcript" and "attribution_identities" in artifact:
            identities = artifact["attribution_identities"]
            segments = [{**segment, "effective_speaker": identities.get(segment["id"])} for segment in segments]
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
            result = await analyze_memories(snapshot, window, artifact["items"], deadline=deadline,
                **({"validate_context": validate_manual_source} if control.get("active") else {}))
            for atom in result["items"]:
                atom = dict(atom)
                if input_source == "summary":
                    atom["source"] = "summary"
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
                apply_from_memory, meeting_id, self.owner, record["transcript_hash"], snapshot["revision"],
                artifact["context_labels_revision"], artifact["context_labels"],
            )
        for item in artifact["items"]:
            if item["id"] in artifact["published_ids"]:
                continue
            await run_db(memory_db.assert_publishable, meeting_id, self.owner, record["transcript_hash"])
            # Older checkpoints must replay their exact publication after a lost receipt.
            tags = item["tags"] if "tags" in item else ["meeting-memory", f"meeting:{meeting_id}", item["kind"]]
            await run_db(publish, item["id"], memory_content(snapshot, item),
                         repo=snapshot.get("project"), tags=tags,
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
