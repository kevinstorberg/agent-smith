from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from services.api.routers.base import delete_response, empty_to_none, require_found
from services.api.routers.profiles import profile_change, router as profiles_router
from services.api.routers.meeting_vocabulary import router as vocabulary_router
from services.meetings import db, digestion_db, management_db, memory_db, profile_db
from services.meetings import labels_db

router = APIRouter()
router.include_router(profiles_router, prefix="/profiles", include_in_schema=False)
router.include_router(vocabulary_router, prefix="/vocabulary", tags=["meeting vocabulary"])


class MeetingParticipantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(None, max_length=320)
    profile_id: UUID | None = None
    speaker_key: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    segment_id: str | None = Field(None, min_length=1, max_length=200)


class MeetingParticipantsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)
    participants: list[MeetingParticipantRequest] = Field(max_length=200)
    expected_transcript_hash: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")


class MeetingLabelsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)
    labels: list[str] = Field(max_length=8)
    expected_meeting_revision: int | None = Field(default=None, ge=0, strict=True)


class MeetingLabelSuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0, strict=True)


def _label_change(action, *args):
    try:
        return action(*args)
    except labels_db.MeetingLabelsNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except labels_db.MeetingLabelsConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


def _meeting_change(action, *args):
    try:
        return action(*args)
    except management_db.MeetingNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except (management_db.MeetingManagementConflict, profile_db.ProfileRevisionConflict) as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.get("")
def list_all(
    source: str = Query("", max_length=100),
    project: str = Query("", max_length=200),
    q: str = Query("", max_length=1000),
    after: str = Query(""),
    before: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    labels: list[str] = Query(default_factory=list, max_length=8),
):
    try:
        return db.list_summaries(
            source=empty_to_none(source), project=empty_to_none(project), query=empty_to_none(q),
            after=empty_to_none(after), before=empty_to_none(before), limit=limit, offset=offset,
            labels=labels or None,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.get("/status")
def status(source: str = Query("", max_length=100)):
    if source and not source.strip():
        raise HTTPException(status_code=422, detail="Meeting source filter must be nonblank")
    return db.source_status(empty_to_none(source))


@router.get("/{summary_id}")
def get_one(summary_id: UUID):
    key = str(summary_id)
    return require_found(db.get_summary(key), "Meeting summary", key)


@router.patch("/{summary_id}/labels")
def update_labels(summary_id: UUID, body: MeetingLabelsRequest):
    return _label_change(labels_db.update, str(summary_id), body.expected_revision, body.labels, body.expected_meeting_revision)


@router.post("/{summary_id}/labels/suggest")
async def suggest_labels(summary_id: UUID, body: MeetingLabelSuggestionRequest):
    from services.meetings.analysis import AnalysisBudgetExpired
    from services.meetings.label_analysis import LabelAnalysisError, SUGGEST_SECONDS, suggest_labels as suggest
    from services.meetings.service import run_db

    key = str(summary_id)
    attempt = asyncio.timeout(SUGGEST_SECONDS)
    try:
        async with attempt:
            original = await run_db(_label_change, labels_db.snapshot, key, body.expected_revision)
            result = await suggest(original, deadline=attempt.when())
            latest = await run_db(_label_change, labels_db.snapshot, key, body.expected_revision)
            if latest["revision"] != original["revision"]:
                raise HTTPException(status_code=409, detail="Meeting summary changed; generate a new suggestion")
    except AnalysisBudgetExpired:
        raise HTTPException(status_code=504, detail="Label suggestions timed out; saved labels are unchanged") from None
    except TimeoutError:
        if not attempt.expired():
            raise
        raise HTTPException(status_code=504, detail="Label suggestions timed out; saved labels are unchanged") from None
    except LabelAnalysisError as error:
        raise HTTPException(status_code=502, detail=f"Label suggestions failed ({error.error_type}); saved labels are unchanged") from None
    return {"labels": result["labels"], "labels_revision": original["labels_revision"], "meeting_revision": original["revision"]}


@router.get("/{summary_id}/participants")
def get_participants(summary_id: UUID):
    key = str(summary_id)
    return require_found(management_db.get_participants(key), "Meeting", key)


@router.put("/{summary_id}/participants")
def update_participants(summary_id: UUID, body: MeetingParticipantsRequest):
    entries = [person.model_dump(mode="json", exclude_none=True) for person in body.participants]
    return _meeting_change(management_db.update_participants, str(summary_id), body.expected_revision, entries, body.expected_transcript_hash)


@router.post("/{summary_id}/identify-participants")
def identify_participants(summary_id: UUID):
    from services.meetings.speaker_db import request_identification

    return _meeting_change(request_identification, str(summary_id))


@router.post("/{summary_id}/process")
def process_meeting(summary_id: UUID):
    return _meeting_change(management_db.request_processing, str(summary_id))


@router.get("/{summary_id}/transcript")
def get_transcript(
    summary_id: UUID,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    key = str(summary_id)
    return require_found(digestion_db.get_transcript(key, limit=limit, offset=offset), "Meeting summary", key)


@router.delete("/{summary_id}/transcript")
def delete_transcript(summary_id: UUID):
    key = str(summary_id)
    require_found(db.get_summary(key), "Meeting summary", key)
    digestion_db.delete_transcript(key)
    return delete_response(key)


@router.post("/{summary_id}/transcript/retry")
def retry_transcript(summary_id: UUID):
    key = str(summary_id)
    require_found(db.get_summary(key), "Meeting summary", key)
    try:
        digestion_db.retry_transcript(key)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return {"success": True}


@router.get("/{summary_id}/memories")
def get_memories(summary_id: UUID):
    key = str(summary_id)
    return require_found(memory_db.get_memories(key), "Meeting summary", key)


@router.post("/{summary_id}/memories/retry")
def retry_memories(summary_id: UUID):
    key = str(summary_id)
    require_found(db.get_summary(key), "Meeting summary", key)
    try:
        memory_db.retry_memories(key)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return {"success": True}


@router.get("/{summary_id}/profiles")
def get_meeting_profiles(summary_id: UUID):
    key = str(summary_id)
    return require_found(profile_db.meeting_profiles(key), "Meeting summary", key)


@router.post("/{summary_id}/profiles/retry")
def retry_profiles(summary_id: UUID):
    key = str(summary_id)
    require_found(db.get_summary(key), "Meeting summary", key)
    profile_change(profile_db.retry_profiles, key)
    return {"success": True}
