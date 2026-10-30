from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedMeeting(StrictRequest):
    provider: str = Field(min_length=1, max_length=100, strict=True)
    account_key: str = Field(min_length=1, max_length=100, strict=True)
    source_name: str = Field(min_length=1, max_length=100, strict=True)
    meeting_revision: int = Field(ge=1, strict=True)
    transcript_hash: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    participants_revision: int = Field(ge=0, strict=True)
    speaker_updated_at: str | None
    profile_updated_at: str | None
    memory_updated_at: str | None

    @field_validator("speaker_updated_at", "profile_updated_at", "memory_updated_at")
    @classmethod
    def timestamp(cls, value: str | None) -> str | None:
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.utcoffset() is None:
                raise ValueError("Stage timestamp must include its timezone")
            return parsed.isoformat()
        return None


class SelectedMeeting(StrictRequest):
    id: UUID
    expected: ExpectedMeeting


class TargetProfile(StrictRequest):
    id: UUID
    expected_revision: int = Field(ge=1, strict=True)


class AnalysisRequest(StrictRequest):
    request_id: UUID
    confirmed: Literal[True]
    scope: Literal["profiles", "memories", "both"] = "profiles"
    target_profile: TargetProfile | None = None
    meetings: list[SelectedMeeting] = Field(min_length=1, max_length=10)

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation must be true")
        return value

    @model_validator(mode="after")
    def valid_selection(self) -> AnalysisRequest:
        if len({item.id for item in self.meetings}) != len(self.meetings):
            raise ValueError("Select each meeting only once")
        if self.target_profile and self.scope == "memories":
            raise ValueError("A target profile requires profile analysis")
        return self


class ResumeRequest(StrictRequest):
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        return AnalysisRequest.explicit_confirmation(value)
