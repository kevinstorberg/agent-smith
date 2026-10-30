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
    def __init__(self, source: str | None = None, profile_id: str | None = None) -> None:
        from uuid import UUID

        self.provider = build_context_provider()
        super().__init__(self._release_all, get_record=self.provider.get_record)
        self.source = source
        self.profile_id = str(UUID(profile_id)) if profile_id is not None else None
        self.analysis_target_id: str | None = None
        self.profile_report: dict = {"outcome": "idle"}
        self.assessment_report: dict = {"outcome": "idle", "profiles": 0}

    def _release_all(self, owner: str) -> None:
        from services.personas import assessment_db

        try:
            assessment_db.release_owner(owner)
        finally:
            self.provider.release_owner(owner)

    async def prepare(self) -> None:
        if self.profile_id is not None:
            return
        self.record = await run_db(self.provider.claim, self.owner, source=self.source)
        self.analysis_target_id = (self.record or {}).get("analysis_target_profile_id")
        if self.record is not None and (
            not isinstance(self.record.get("context_id"), str) or not self.record["context_id"].strip()
            or not isinstance(self.record.get("context_hash"), str) or not self.record["context_hash"].strip()
            or not isinstance(self.record.get("segments"), list)
        ):
            raise ValueError("Persona context requires a stable ID, content hash and segment list")

    async def build_profiles(self) -> None:
        if self.record is not None:
            await self.run_stage("profile", self.profile_report, self._profile_work, self.provider.record_failure, budget=AGENT_SECONDS)

    async def build_assessments(self) -> None:
        import asyncio

        from services.personas import assessment, assessment_db

        if self.remaining < 50:
            self.assessment_report.update(outcome="continued")
            return
        if self.analysis_target_id and self.profile_report.get("outcome") != "done":
            return
        snapshot = await run_db(assessment_db.claim, self.owner, self.profile_id or self.analysis_target_id)
        if not snapshot:
            return
        if snapshot.get("skipped"):
            self.assessment_report.update(outcome="done", unchanged=True, profile_ids=[snapshot["id"]])
            return
        self.assessment_report.update(profile_ids=[snapshot["id"]])
        deadline = asyncio.get_running_loop().time() + min(AGENT_SECONDS, self.remaining - 10)
        try:
            async with asyncio.timeout_at(deadline):
                row, claims = snapshot["profile"], snapshot["claims"]
                directed = assessment_db.relationship_insufficient(row)
                can_assess_edges = any(sum(claim.get("canonical_target_id") == item["target_id"] for claim in claims) >= 2 for item in directed)
                if not claims or not assessment_db.insufficient(row) and not can_assess_edges:
                    candidates = assessment_db.insufficient(row)
                else:
                    result = await assessment.synthesize(row, claims, deadline=deadline)
                    candidates = result["sections"]
                    directed = result.get("relationships", [])
                await run_db(assessment_db.apply, self.owner, snapshot, candidates, directed)
            self.assessment_report.update(outcome="done", profiles=1)
        except Exception as error:
            category = processing.failure_category(error)
            await run_db(assessment_db.fail, snapshot["id"], self.owner, category)
            self.assessment_report.update(outcome="failed", error_type=category)

    async def _profile_work(self, record: dict, *, deadline: float) -> None:
        try:
            await self._update_profiles(record, deadline=deadline)
        except profile_db.ProfileRevisionConflict:
            await run_db(self.provider.reset_progress, record["context_id"], self.owner, record["context_hash"])
            raise

    async def _update_profiles(self, record: dict, *, deadline: float) -> None:
        from services.graphs.model_config import resolve_model_id
        from services.meetings.profile_analysis import analyze_profiles
        from services.meetings import profile_directory

        context_id = record["context_id"]
        validate_context = getattr(self.provider, "validate_context", None)
        if validate_context:
            record = await run_db(validate_context, record, self.owner)
        self.analysis_target_id = record.get("analysis_target_profile_id")
        participants_revision = record.get("participants_revision", 0)
        analysis_snapshot, participants, profiles = await run_db(self.provider.prepare_context, record)
        if self.analysis_target_id:
            analysis_snapshot = {**analysis_snapshot, "analysis_target_profile_id": self.analysis_target_id}
        artifact = copy.deepcopy(record["profile_artifact"]) or {
            "version": 1, "offset": 0, "items": [], "metadata_updates": [], "reason": "",
            "model": resolve_model_id("persona", "curator"), "prompt_version": 1,
            "expected_revisions": {profile["id"]: profile["revision"] for profile in profiles},
            "participants_revision": participants_revision,
        }
        if artifact["version"] != 1:
            raise ValueError("Unsupported persona profile artifact version")
        if record.get("analysis_request_id"):
            artifact["manual_request_id"] = record["analysis_request_id"]
        if artifact.get("participants_revision", 0) != participants_revision:
            raise profile_db.ProfileRevisionConflict("Context participants changed; rebuild the profile candidate")
        restored = profile_directory.extend_catalog(participants, artifact)
        if len(restored) != len(participants):
            participants = restored
            profiles = await run_db(profile_db.load_profiles, participants)
        if artifact["expected_revisions"] != {profile["id"]: profile["revision"] for profile in profiles}:
            raise profile_db.ProfileRevisionConflict("Participant profile changed; rebuild the profile candidate")
        segments = expanded_segments(record["segments"])
        artifact["total_units"] = len(segments)
        await run_db(self.provider.save_progress, context_id, self.owner, record["context_hash"], artifact)
        while artifact["offset"] < len(segments):
            window, end = transcript_window(segments, artifact["offset"])
            if validate_context:
                await run_db(validate_context, record, self.owner)
            result = await analyze_profiles(
                analysis_snapshot, window, artifact["items"], participants=participants,
                profiles=profiles, memories=[], previous_metadata=artifact.get("metadata_updates", []), deadline=deadline,
            )
            if self.analysis_target_id:
                result = {**result, "items": [item for item in result["items"] if item["subject_id"] == self.analysis_target_id],
                    "metadata_updates": [item for item in result.get("metadata_updates", []) if item["subject_id"] == self.analysis_target_id]}
            extended = profile_directory.checkpoint_targets(artifact, participants, result)
            if len(extended) != len(participants):
                participants = extended
                profiles = await run_db(profile_db.load_profiles, participants)
            artifact["items"].extend(result["items"])
            if result.get("metadata_updates"):
                artifact.setdefault("metadata_updates", []).extend(result["metadata_updates"])
            artifact.update(offset=end, reason=result.get("reason", ""))
            await run_db(self.provider.save_progress, context_id, self.owner, record["context_hash"], artifact)
        profile_ids = await run_db(self.provider.apply_profiles, context_id, self.owner, record["context_hash"], artifact, participants)
        record.update(profile_status="done", profile_artifact=artifact)
        self.profile_report.update(outcome="done", profiles=len(profile_ids), profile_ids=profile_ids)
