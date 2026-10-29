from __future__ import annotations

import copy

from services.meetings import profile_db, processing
from services.meetings.service import run_db
from services.personas.factory import build_context_provider

AGENT_SECONDS = processing.AGENT_SECONDS
WINDOW_CHARS = processing.WINDOW_CHARS
WINDOW_SEGMENTS = processing.WINDOW_SEGMENTS


def expanded_segments(segments):
    return processing.expanded_segments(segments, max_chars=WINDOW_CHARS)


def transcript_window(segments, offset):
    return processing.transcript_window(segments, offset, max_chars=WINDOW_CHARS, max_segments=WINDOW_SEGMENTS)


class PersonaRun(processing.ProcessingRun):
    def __init__(self, source: str | None = None) -> None:
        self.provider = build_context_provider()
        super().__init__(self.provider.release_owner, get_record=self.provider.get_record)
        self.source = source
        self.profile_report: dict = {"outcome": "idle"}

    async def prepare(self) -> None:
        self.record = await run_db(self.provider.claim, self.owner, source=self.source)
        if self.record is not None and (
            not isinstance(self.record.get("context_id"), str) or not self.record["context_id"].strip()
            or not isinstance(self.record.get("context_hash"), str) or not self.record["context_hash"].strip()
            or not isinstance(self.record.get("segments"), list)
        ):
            raise ValueError("Persona context requires a stable ID, content hash and segment list")

    async def build_profiles(self) -> None:
        if self.record is not None:
            await self.run_stage("profile", self.profile_report, self._profile_work, self.provider.record_failure, budget=AGENT_SECONDS)

    async def _profile_work(self, record: dict, *, deadline: float) -> None:
        try:
            await self._update_profiles(record, deadline=deadline)
        except profile_db.ProfileRevisionConflict:
            await run_db(self.provider.reset_progress, record["context_id"], self.owner, record["context_hash"])
            raise

    async def _update_profiles(self, record: dict, *, deadline: float) -> None:
        from services.graphs.model_config import resolve_model_id
        from services.meetings.profile_analysis import analyze_profiles

        context_id = record["context_id"]
        participants_revision = record.get("participants_revision", 0)
        analysis_snapshot, participants, profiles = await run_db(self.provider.prepare_context, record)
        artifact = copy.deepcopy(record["profile_artifact"]) or {
            "version": 1, "offset": 0, "items": [], "reason": "",
            "model": resolve_model_id("persona", "curator"), "prompt_version": 1,
            "expected_revisions": {profile["id"]: profile["revision"] for profile in profiles},
            "participants_revision": participants_revision,
        }
        if artifact["version"] != 1:
            raise ValueError("Unsupported persona profile artifact version")
        if artifact.get("participants_revision", 0) != participants_revision:
            raise profile_db.ProfileRevisionConflict("Context participants changed; rebuild the profile candidate")
        if artifact["expected_revisions"] != {profile["id"]: profile["revision"] for profile in profiles}:
            raise profile_db.ProfileRevisionConflict("Participant profile changed; rebuild the profile candidate")
        segments = expanded_segments(record["segments"])
        artifact["total_units"] = len(segments)
        await run_db(self.provider.save_progress, context_id, self.owner, record["context_hash"], artifact)
        while artifact["offset"] < len(segments):
            window, end = transcript_window(segments, artifact["offset"])
            result = await analyze_profiles(
                analysis_snapshot, window, artifact["items"], participants=participants,
                profiles=profiles, memories=[], deadline=deadline,
            )
            artifact["items"].extend(result["items"])
            artifact.update(offset=end, reason=result.get("reason", ""))
            await run_db(self.provider.save_progress, context_id, self.owner, record["context_hash"], artifact)
        profile_ids = await run_db(self.provider.apply_profiles, context_id, self.owner, record["context_hash"], artifact, participants)
        record.update(profile_status="done", profile_artifact=artifact)
        self.profile_report.update(outcome="done", profiles=len(profile_ids), profile_ids=profile_ids)
