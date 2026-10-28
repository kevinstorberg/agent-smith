from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from services.api.routers.base import delete_response, empty_to_none, require_found
from services.meetings import db, digestion_db, memory_db, profile_db

router = APIRouter()


class ProfileRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)


class ClaimCorrectionRequest(ProfileRevisionRequest):
    action: Literal["correct", "reject"]
    content: str | None = Field(None, max_length=2000)
    reason: str = Field(min_length=1, max_length=2000)


def _profile_change(action, *args):
    try:
        return action(*args)
    except profile_db.ProfileRevisionConflict as error:
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
):
    try:
        return db.list_summaries(
            source=empty_to_none(source), project=empty_to_none(project), query=empty_to_none(q),
            after=empty_to_none(after), before=empty_to_none(before), limit=limit, offset=offset,
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
    _profile_change(profile_db.retry_profiles, key)
    return {"success": True}


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: UUID):
    key = str(profile_id)
    return require_found(profile_db.get_profile(key), "Participant profile", key)


@router.post("/profiles/{profile_id}/claims/{claim_id}")
def correct_profile_claim(profile_id: UUID, claim_id: UUID, body: ClaimCorrectionRequest):
    key = str(profile_id)
    require_found(profile_db.get_profile(key), "Participant profile", key)
    return _profile_change(profile_db.correct_claim, key, str(claim_id), body.expected_revision, body.action, body.content, body.reason)


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: UUID, body: ProfileRevisionRequest):
    key = str(profile_id)
    require_found(profile_db.get_profile(key), "Participant profile", key)
    _profile_change(profile_db.delete_profile, key, body.expected_revision)
    return delete_response(key)
