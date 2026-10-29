from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.api.routers.base import delete_response, empty_to_none, require_found
from services.meetings import profile_db

router = APIRouter()


class ProfileRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)


class ClaimCorrectionRequest(ProfileRevisionRequest):
    action: Literal["correct", "reject"]
    content: str | None = Field(None, max_length=2000)
    reason: str = Field(min_length=1, max_length=2000)


class ProfileMetadataRequest(ProfileRevisionRequest):
    tags: list[str] | None = Field(None, max_length=profile_db.MAX_TAGS)
    starred: bool | None = Field(None, strict=True)

    @model_validator(mode="before")
    @classmethod
    def require_metadata(cls, value):
        if isinstance(value, dict):
            fields = {key for key in ("tags", "starred") if key in value}
            if not fields or any(value[key] is None for key in fields):
                raise ValueError("Provide non-null tags or starred state")
        return value


class MergeProfilesRequest(ProfileRevisionRequest):
    target_id: UUID
    target_revision: int = Field(ge=1, strict=True)


class ProfileAliasRequest(ProfileRevisionRequest):
    email: str = Field(min_length=1, max_length=320)


def profile_change(action, *args, **kwargs):
    try:
        return action(*args, **kwargs)
    except profile_db.ProfileRevisionConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.get("")
def list_all(
    q: str = Query("", max_length=1000),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    tags: list[str] = Query(default_factory=list, max_length=profile_db.MAX_TAGS),
    starred: bool | None = Query(None),
    sort: str = Query("created_at_desc"),
):
    try:
        return profile_db.list_profiles(query=empty_to_none(q), limit=limit, offset=offset, tags=tags, starred=starred, sort=sort)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.get("/{profile_id}")
def get_one(profile_id: UUID):
    key = str(profile_id)
    return require_found(profile_db.get_profile(key), "Participant profile", key)


@router.patch("/{profile_id}")
def update_metadata(profile_id: UUID, body: ProfileMetadataRequest):
    key = str(profile_id)
    require_found(profile_db.get_profile(key), "Participant profile", key)
    return profile_change(profile_db.update_metadata, key, body.expected_revision, **body.model_dump(include={"tags", "starred"}, exclude_unset=True))


@router.post("/{profile_id}/merge")
def merge_profiles(profile_id: UUID, body: MergeProfilesRequest):
    key, target = str(profile_id), str(body.target_id)
    require_found(profile_db.get_profile(key), "Participant profile", key)
    require_found(profile_db.get_profile(target), "Participant profile", target)
    return profile_change(profile_db.merge_profiles, key, target, body.expected_revision, body.target_revision)


@router.post("/{profile_id}/aliases")
def link_alias(profile_id: UUID, body: ProfileAliasRequest):
    key = str(profile_id)
    require_found(profile_db.get_profile(key), "Participant profile", key)
    return profile_change(profile_db.link_alias, key, body.email, body.expected_revision)


@router.post("/{profile_id}/claims/{claim_id}")
def correct_claim(profile_id: UUID, claim_id: UUID, body: ClaimCorrectionRequest):
    key = str(profile_id)
    require_found(profile_db.get_profile(key), "Participant profile", key)
    return profile_change(profile_db.correct_claim, key, str(claim_id), body.expected_revision, body.action, body.content, body.reason)


@router.delete("/{profile_id}")
def delete_profile(profile_id: UUID, body: ProfileRevisionRequest):
    key = str(profile_id)
    require_found(profile_db.get_profile(key), "Participant profile", key)
    profile_change(profile_db.delete_profile, key, body.expected_revision)
    return delete_response(key)
