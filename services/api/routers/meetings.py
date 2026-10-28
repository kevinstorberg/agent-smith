from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from services.api.routers.base import delete_response, empty_to_none, require_found
from services.meetings import db, digestion_db

router = APIRouter()


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
