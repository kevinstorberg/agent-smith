from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services.api.routers.base import delete_response
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


def _change(function, *args):
    try:
        return function(*args)
    except vocabulary_db.VocabularyConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.get("")
def list_terms():
    return vocabulary_db.list_terms()


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
