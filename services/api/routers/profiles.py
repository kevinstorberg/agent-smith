from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.api.routers.base import delete_response, empty_to_none, require_found
from services.meetings import profile_db, profile_fields, relationship_db, relationship_card_db
from services.meetings.outputs import ProfileCategory, ProfileEpistemic, ProfileConfidence, ProfileReviewStatus, ProfileClaimSort
from services.personas import assessment_db, revisions

router = APIRouter()


class CreateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=profile_db.MAX_PROFILE_NAME_LENGTH, strict=True)
    email: str | None = Field(None, min_length=1, max_length=320, strict=True)


class ProfileRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)


class ClaimCorrectionRequest(ProfileRevisionRequest):
    action: Literal["correct", "reject"]
    content: str | None = Field(None, max_length=2000)
    reason: str = Field(min_length=1, max_length=2000)


class ProfileMetadataRequest(ProfileRevisionRequest):
    display_name: str | None = Field(None, min_length=1, max_length=profile_db.MAX_PROFILE_NAME_LENGTH, strict=True)
    tags: list[str] | None = Field(None, max_length=profile_db.MAX_TAGS)
    starred: bool | None = Field(None, strict=True)
    metadata: dict[str, str] | None = Field(None, max_length=7)
    nicknames: list[str] | None = Field(None, max_length=20)
    section_notes: dict[str, str] | None = Field(None, max_length=6)
    allow_agent_sections: list[str] | None = Field(None, max_length=6)

    @model_validator(mode="before")
    @classmethod
    def require_metadata(cls, value):
        if isinstance(value, dict):
            fields = {key for key in ("display_name", "tags", "starred", "metadata", "nicknames", "section_notes", "allow_agent_sections") if key in value}
            if not fields or any(value[key] is None for key in fields):
                raise ValueError("Provide non-null profile fields to update")
        return value


class MergeProfilesRequest(ProfileRevisionRequest):
    target_id: UUID
    target_revision: int = Field(ge=1, strict=True)


class ProfileAliasRequest(ProfileRevisionRequest):
    email: str = Field(min_length=1, max_length=320)


class RelationshipCreate(ProfileRevisionRequest):
    target_id: UUID
    target_revision: int = Field(ge=1, strict=True)
    label: str = Field(default="", max_length=200, strict=True)
    notes: str = Field(default="", max_length=4000, strict=True)


class RelationshipUpdate(ProfileRevisionRequest):
    label: str | None = Field(None, max_length=200, strict=True)
    notes: str | None = Field(None, max_length=4000, strict=True)
    allow_agent_notes: bool = Field(default=False, strict=True)

    @model_validator(mode="before")
    @classmethod
    def require_fields(cls, value):
        if isinstance(value, dict):
            fields = {key for key in ("label", "notes") if key in value}
            if (not fields and value.get("allow_agent_notes") is not True) or any(value[key] is None for key in fields):
                raise ValueError("Provide relationship fields or release automatic notes updates")
            if "notes" in fields and value.get("allow_agent_notes"):
                raise ValueError("Notes cannot be edited and released together")
        return value


class RelationshipCardCreate(ProfileRevisionRequest):
    name: str = Field(min_length=1, max_length=200, strict=True)
    profile_id: UUID | None = None
    target_revision: int | None = Field(None, ge=1, strict=True)
    notes: str | None = Field(None, max_length=4000, strict=True)
    label: str = Field(default="", max_length=200, strict=True)
    assignment_version: str | None = Field(None, pattern="^[0-9a-f]{64}$", strict=True)

    @model_validator(mode="before")
    @classmethod
    def non_null_notes(cls, value):
        if isinstance(value, dict) and "notes" in value and value["notes"] is None:
            raise ValueError("Relationship notes must be text; use an empty string to clear them")
        return value


class RelationshipCardVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern="^[0-9a-f]{64}$", strict=True)


class RelationshipCardUpdate(RelationshipCardVersion):
    name: str | None = Field(None, min_length=1, max_length=200, strict=True)
    profile_id: UUID | None = None
    target_revision: int | None = Field(None, ge=1, strict=True)
    notes: str | None = Field(None, max_length=4000, strict=True)
    label: str | None = Field(None, max_length=200, strict=True)
    allow_agent_notes: bool = Field(default=False, strict=True)

    @model_validator(mode="before")
    @classmethod
    def require_change(cls, value):
        if isinstance(value, dict):
            fields = {key for key in ("name", "notes", "label", "profile_id") if key in value}
            if not fields and value.get("allow_agent_notes") is not True:
                raise ValueError("Provide relationship fields or release automatic updates")
            if any(value[key] is None for key in fields - {"profile_id"}):
                raise ValueError("Relationship fields must be text; use an empty notes string to clear")
            if "notes" in fields and value.get("allow_agent_notes"):
                raise ValueError("Notes cannot be edited and released together")
        return value


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
    sort: str = Query(profile_db.DEFAULT_PROFILE_SORT),
):
    try:
        return profile_db.list_profiles(query=empty_to_none(q), limit=limit, offset=offset, tags=tags, starred=starred, sort=sort)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.get("/metadata-options")
def metadata_options() -> dict[str, tuple[str, ...]]:
    return profile_fields.METADATA_CHOICES


@router.get("/{profile_id}")
def get_one(profile_id: UUID, include_evidence: bool = True):
    key = str(profile_id)
    return require_found(profile_change(profile_db.get_profile, key, include_evidence=include_evidence), "Participant profile", key)


@router.get("/{profile_id}/claims")
def list_claims(profile_id: UUID, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                q: str = Query("", max_length=1000), category: ProfileCategory | None = None,
                epistemic: ProfileEpistemic | None = None, confidence: ProfileConfidence | None = None,
                status: ProfileReviewStatus | None = None, target_id: UUID | None = None,
                sort: ProfileClaimSort = "oldest"):
    key = str(profile_id)
    return require_found(profile_change(profile_db.list_claims, key, limit=limit, offset=offset, query=empty_to_none(q),
                         category=category, epistemic=epistemic, confidence=confidence, status=status,
                         target_id=str(target_id) if target_id else None, sort=sort), "Profile", key)


@router.post("", status_code=201)
def create_profile(body: CreateProfileRequest, include_evidence: bool = True):
    return profile_change(profile_db.create_profile, body.display_name, email=body.email, include_evidence=include_evidence)


@router.patch("/{profile_id}")
def update_metadata(profile_id: UUID, body: ProfileMetadataRequest, include_evidence: bool = True):
    key = str(profile_id)
    require_found(profile_db.get_profile(key, include_evidence=False), "Participant profile", key)
    return profile_change(profile_db.update_metadata, key, body.expected_revision, include_evidence=include_evidence,
                          **body.model_dump(include={"display_name", "tags", "starred", "metadata", "nicknames", "section_notes", "allow_agent_sections"}, exclude_unset=True))


@router.get("/{profile_id}/history")
def list_history(profile_id: UUID, limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)):
    return require_found(revisions.list_history(str(profile_id), limit=limit, offset=offset), "Profile", str(profile_id))


@router.get("/{profile_id}/history/{revision_id}")
def get_history(profile_id: UUID, revision_id: int):
    return require_found(revisions.list_history(str(profile_id), revision_id=revision_id), "Profile revision", revision_id)


@router.post("/{profile_id}/rebuild")
async def rebuild(profile_id: UUID, body: ProfileRevisionRequest):
    from services.config import DEVICE_NAME
    from services.jobs.models.job import list_graph_jobs
    from services.jobs.scheduler import execute_job
    from services.jobs.scoping import job_runs_on_device
    from services.meetings.service import run_db

    require_found(await run_db(profile_db.get_profile, str(profile_id)), "Profile", str(profile_id))
    jobs = await run_db(list_graph_jobs, "persona")
    eligible = await run_db(lambda: [job for job in jobs if job_runs_on_device(job["id"], DEVICE_NAME)])
    if not eligible:
        raise HTTPException(status_code=409, detail="Create a Personas graph job enabled on this device before building a profile assessment.")
    key = str(profile_id)
    try:
        requested = await run_db(assessment_db.request, key, body.expected_revision)
    except profile_db.ProfileRevisionConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    job = eligible[0]
    params = {**job["input_params"], "graph_inputs": {"profile_id": requested["id"]}}
    result = await execute_job({**job, "input_params": params})
    return {**result, "job_id": job["id"], "profile_id": requested["id"]}


@router.get("/{profile_id}/relationships")
def list_relationships(profile_id: UUID, include_evidence: bool = True):
    key = str(profile_id)
    profile = require_found(profile_db.get_profile(key, include_evidence=include_evidence), "Profile", key)
    return {"items": profile["relationships"], "total": len(profile["relationships"])}


@router.post("/{profile_id}/relationship-cards", status_code=201)
def create_relationship_card(profile_id: UUID, body: RelationshipCardCreate):
    return profile_change(relationship_card_db.create, str(profile_id), body.expected_revision, body.name,
                          profile_id_target=str(body.profile_id) if body.profile_id else None,
                          target_revision=body.target_revision, notes=body.notes, label=body.label,
                          assignment_version=body.assignment_version)


@router.patch("/{profile_id}/relationship-cards/{card_id}")
def edit_relationship_card(profile_id: UUID, card_id: str, body: RelationshipCardUpdate):
    values = body.model_dump(include={"notes", "label", "name", "target_revision", "allow_agent_notes"}, exclude_unset=True)
    if "profile_id" in body.model_fields_set:
        values["profile_id_target"] = str(body.profile_id) if body.profile_id else None
    return profile_change(relationship_card_db.update, str(profile_id), card_id, body.version, **values)


@router.delete("/{profile_id}/relationship-cards/{card_id}")
def remove_relationship_card(profile_id: UUID, card_id: str, body: RelationshipCardVersion):
    profile_change(relationship_card_db.delete, str(profile_id), card_id, body.version)
    return delete_response(card_id)


@router.post("/{profile_id}/relationships", status_code=201)
def create_relationship(profile_id: UUID, body: RelationshipCreate, include_evidence: bool = True):
    return profile_change(relationship_db.create, str(profile_id), str(body.target_id), body.expected_revision,
                          body.target_revision, body.label, body.notes if "notes" in body.model_fields_set else None, include_evidence=include_evidence)


@router.patch("/{profile_id}/relationships/{relationship_id}")
def edit_relationship(profile_id: UUID, relationship_id: UUID, body: RelationshipUpdate, include_evidence: bool = True):
    return profile_change(relationship_db.update, str(profile_id), str(relationship_id), body.expected_revision, include_evidence=include_evidence,
                          **body.model_dump(include={"label", "notes", "allow_agent_notes"}, exclude_unset=True))


@router.delete("/{profile_id}/relationships/{relationship_id}")
def remove_relationship(profile_id: UUID, relationship_id: UUID, body: ProfileRevisionRequest):
    key = str(relationship_id)
    profile_change(relationship_db.delete, str(profile_id), key, body.expected_revision)
    return delete_response(key)


@router.post("/{profile_id}/merge")
def merge_profiles(profile_id: UUID, body: MergeProfilesRequest, include_evidence: bool = True):
    key, target = str(profile_id), str(body.target_id)
    require_found(profile_db.get_profile(key, include_evidence=False), "Participant profile", key)
    require_found(profile_db.get_profile(target, include_evidence=False), "Participant profile", target)
    return profile_change(profile_db.merge_profiles, key, target, body.expected_revision, body.target_revision, include_evidence=include_evidence)


@router.post("/{profile_id}/aliases")
def link_alias(profile_id: UUID, body: ProfileAliasRequest, include_evidence: bool = True):
    key = str(profile_id)
    require_found(profile_db.get_profile(key, include_evidence=False), "Participant profile", key)
    return profile_change(profile_db.link_alias, key, body.email, body.expected_revision, include_evidence=include_evidence)


@router.post("/{profile_id}/claims/{claim_id}")
def correct_claim(profile_id: UUID, claim_id: UUID, body: ClaimCorrectionRequest, include_evidence: bool = True):
    key = str(profile_id)
    require_found(profile_db.get_profile(key, include_evidence=False), "Participant profile", key)
    return profile_change(profile_db.correct_claim, key, str(claim_id), body.expected_revision, body.action, body.content, body.reason, include_evidence=include_evidence)


@router.delete("/{profile_id}")
def delete_profile(profile_id: UUID, body: ProfileRevisionRequest):
    key = str(profile_id)
    require_found(profile_db.get_profile(key), "Participant profile", key)
    profile_change(profile_db.delete_profile, key, body.expected_revision)
    return delete_response(key)
