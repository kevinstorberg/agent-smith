from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from services.api.routers.base import delete_response, require_found
from services.meetings import vocabulary_db

router = APIRouter()


class TermRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term: str = Field(min_length=1, max_length=200, strict=True)
    definition: str = Field(default="", max_length=2000, strict=True)


class UpdateTermRequest(TermRequest):
    expected_revision: int = Field(ge=1, strict=True)


class DeleteTermRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)


def _change(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except vocabulary_db.VocabularyConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.get("")
def list_terms(q: str = Query("", max_length=1000), limit: int | None = Query(None, ge=1, le=100), offset: int = Query(0, ge=0)):
    return _change(vocabulary_db.list_terms, query=q, limit=limit, offset=offset)


@router.get("/{term_id}")
def get_term(term_id: UUID):
    return require_found(_change(vocabulary_db.get_term, str(term_id)), "Vocabulary term", str(term_id))


@router.post("", status_code=201)
def create_term(body: TermRequest):
    return _change(vocabulary_db.create, body.term, body.definition)


@router.patch("/{term_id}")
def update_term(term_id: UUID, body: UpdateTermRequest):
    return _change(vocabulary_db.update, str(term_id), body.expected_revision, body.term, body.definition)


@router.delete("/{term_id}")
def delete_term(term_id: UUID, body: DeleteTermRequest):
    key = str(term_id)
    _change(vocabulary_db.delete, key, body.expected_revision)
    return delete_response(key)
