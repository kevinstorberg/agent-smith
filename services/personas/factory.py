from __future__ import annotations

import os
from typing import Protocol


class ContextProvider(Protocol):
    """A claimed record supplies context_id/hash, segments, snapshot and profile-stage state."""

    def claim(self, owner: str, *, source: str | None = None) -> dict | None: ...
    def has_requested_work(self, *, source: str | None = None) -> bool: ...
    def get_record(self, context_id: str) -> dict | None: ...
    def prepare_context(self, record: dict) -> tuple[dict, list[dict], list[dict]]: ...
    def save_progress(self, context_id: str, owner: str, context_hash: str, artifact: dict) -> None: ...
    def apply_profiles(self, context_id: str, owner: str, context_hash: str, artifact: dict, participants: list[dict]) -> list[str]: ...
    def reset_progress(self, context_id: str, owner: str, context_hash: str) -> None: ...
    def record_failure(self, context_id: str, owner: str, error_type: str) -> None: ...
    def release_owner(self, owner: str) -> None: ...


class MeetingContextProvider:
    @staticmethod
    def _record(row: dict | None) -> dict | None:
        if row is None:
            return None
        # Keep meeting fields for existing readers; persona orchestration uses normalized keys.
        control = row.get("manual_analysis", {}).get("profile", {})
        target = (control.get("target") or {}).get("id") if control.get("active") else None
        return {**row, "context_id": row["meeting_id"], "context_hash": row["transcript_hash"],
                "segments": row["transcript"].get("segments", []), "analysis_target_profile_id": target,
                "analysis_request_id": control.get("request_id") if control.get("active") else None}

    def claim(self, owner: str, *, source: str | None = None) -> dict | None:
        from services.meetings.digestion_db import claim_profile

        return self._record(claim_profile(source, owner))

    def has_requested_work(self, *, source: str | None = None) -> bool:
        from services.meetings.digestion_db import has_requested_profile_work

        return has_requested_profile_work(source)

    def get_record(self, context_id: str) -> dict | None:
        from services.meetings.digestion_db import get_record

        return self._record(get_record(context_id))

    def validate_context(self, record: dict, owner: str) -> dict:
        from services.meetings import digestion_db, manual_stage

        control = record.get("manual_analysis", {}).get("profile", {})
        if not control.get("active"):
            return record
        current = manual_stage.before_analysis(record["context_id"], owner, record["context_hash"], "profile")
        if not current:
            raise manual_stage.ManualAnalysisInputChanged("Manual profile analysis control was removed")
        target_id = (current.get("target") or {}).get("id")
        snapshot = digestion_db.get_context(record["context_id"])
        return {**record, "snapshot": {**snapshot, **({"analysis_target_profile_id": target_id} if target_id else {})},
                "analysis_target_profile_id": target_id, "analysis_request_id": current["request_id"]}

    def prepare_context(self, record: dict) -> tuple[dict, list[dict], list[dict]]:
        from services.meetings import profile_db
        from services.meetings.participants import meeting_participants

        from services.meetings.speaker_db import context_snapshot

        snapshot = context_snapshot(record)
        participants = profile_db.resolve_participants(meeting_participants(snapshot, record["segments"]))
        participants = profile_db.include_linked_profiles(participants)
        return snapshot, participants, profile_db.load_profiles(participants)

    def save_progress(self, context_id: str, owner: str, context_hash: str, artifact: dict) -> None:
        from services.meetings.profile_db import save_progress

        save_progress(context_id, owner, context_hash, artifact)

    def apply_profiles(self, context_id: str, owner: str, context_hash: str, artifact: dict, participants: list[dict]) -> list[str]:
        from services.meetings.profile_db import apply_profiles

        return apply_profiles(context_id, owner, context_hash, artifact, participants)

    def reset_progress(self, context_id: str, owner: str, context_hash: str) -> None:
        from services.meetings.profile_db import reset_progress

        reset_progress(context_id, owner, context_hash)

    def record_failure(self, context_id: str, owner: str, error_type: str) -> None:
        from services.meetings.profile_db import record_failure

        record_failure(context_id, owner, error_type)

    def release_owner(self, owner: str) -> None:
        from services.meetings.digestion_db import release_profile_owner

        release_profile_owner(owner)


def build_context_provider(name: str | None = None) -> ContextProvider:
    name = os.environ.get("PERSONA_CONTEXT_PROVIDER", "meetings") if name is None else name
    try:
        builder = _PROVIDERS[name]
    except (KeyError, TypeError):
        raise ValueError(f"Unsupported persona context provider; expected {', '.join(_PROVIDERS)}") from None
    return builder()


_PROVIDERS = {"meetings": MeetingContextProvider}
