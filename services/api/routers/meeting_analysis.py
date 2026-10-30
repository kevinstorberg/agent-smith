from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from services.api.routers.base import empty_to_none, require_found
from services.meetings import manual_analysis, manual_candidates, manual_stage, profile_db
from services.meetings.manual_analysis_contracts import AnalysisRequest, ResumeRequest

router = APIRouter()


def analysis_change(action, *args, **kwargs):
    try:
        return action(*args, **kwargs)
    except manual_analysis.AnalysisNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except profile_db.ProfileRevisionConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.get("/candidates")
def candidates(profile_id: UUID | None = None, related: bool = True, q: str = Query("", max_length=1000),
               search_transcript: bool = False, source: str | None = None, after: str | None = None,
               before: str | None = None, meeting_id: UUID | None = None,
               limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)):
    return analysis_change(manual_candidates.list_candidates, profile_id=str(profile_id) if profile_id else None,
        related=related, query=empty_to_none(q), search_transcript=search_transcript, source=source,
        after=after, before=before, meeting_id=str(meeting_id) if meeting_id else None, limit=limit, offset=offset)


@router.post("/requests", status_code=202)
def create_request(body: AnalysisRequest):
    return analysis_change(manual_analysis.request_analysis, body)


@router.get("/requests/{request_id}")
def request_progress(request_id: UUID):
    return require_found(analysis_change(manual_analysis.get_request, str(request_id)), "Analysis request", request_id)


@router.post("/requests/{request_id}/resume", status_code=202)
def resume_request(request_id: UUID, body: ResumeRequest):
    return analysis_change(manual_stage.resume_request, str(request_id))
