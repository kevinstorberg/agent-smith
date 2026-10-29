from __future__ import annotations

from typing import Annotated, Literal, get_args

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

MemoryKind = Literal["fact", "decision", "commitment", "constraint", "preference", "lesson", "question"]
_TOPIC_TAG_LIMIT = 50


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("Content must be nonblank")
    return value.strip()


_Content = Annotated[str, AfterValidator(_nonblank)]


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Evidence(_Output):
    segment_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=4000)


class MemoryItem(_Output):
    content: _Content = Field(min_length=1, max_length=4000)
    kind: MemoryKind
    tags: list[Annotated[str, Field(min_length=1, max_length=_TOPIC_TAG_LIMIT)]] = Field(min_length=1, max_length=8)
    evidence: list[Evidence] = Field(min_length=1, max_length=10)

    @field_validator("tags")
    @classmethod
    def topical_tags(cls, values: list[str]) -> list[str]:
        tags = []
        for value in values:
            tag = "-".join(value.strip().lower().split())
            if not tag or len(tag) > _TOPIC_TAG_LIMIT or tag == "meeting-memory" or tag.startswith("meeting:"):
                raise ValueError("Use short topic tags, not meeting origin identifiers")
            if tag not in tags:
                tags.append(tag)
        if not set(tags).difference(get_args(MemoryKind)):
            raise ValueError("Include a topic, not only memory classifications")
        return tags


class MemorySubmission(_Output):
    items: list[MemoryItem] = Field(max_length=20)
    reason: str = Field(default="", max_length=2000)


class ProfileClaim(_Output):
    subject_id: str = Field(min_length=1, max_length=200)
    target_id: str | None = Field(default=None, min_length=1, max_length=200)
    category: Literal["driver", "strength", "development_area", "role", "priority", "communication", "decision_pattern", "perception", "interaction", "relationship", "uncertainty"]
    epistemic: Literal["self_report", "observed", "inference"]
    confidence: Literal["low", "medium", "high"]
    content: _Content = Field(min_length=1, max_length=2000)
    rationale: str = Field(default="", max_length=2000)
    evidence: list[Evidence] = Field(min_length=1, max_length=10)

    @field_validator("rationale")
    @classmethod
    def clean_rationale(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def grounded_classification(self):
        if self.target_id == self.subject_id:
            raise ValueError("A directed claim must target a different participant")
        if self.category in {"perception", "relationship"} and self.target_id is None:
            raise ValueError("Perception and relationship claims require a directed target participant")
        if self.epistemic == "inference" and (self.confidence == "high" or not self.rationale):
            raise ValueError("Inferences require a rationale and low or medium confidence")
        return self


class ProfileMetadataPatch(_Output):
    subject_id: str = Field(min_length=1, max_length=200)
    fields: dict[str, str] = Field(min_length=1, max_length=7)
    evidence: list[Evidence] = Field(min_length=1, max_length=10)

    @field_validator("fields")
    @classmethod
    def valid_fields(cls, value: dict[str, str]) -> dict[str, str]:
        from services.meetings import profile_fields

        result = profile_fields.fields(value, profile_fields.METADATA_FIELDS, "metadata")
        if any(not item for item in result.values()):
            raise ValueError("Agent metadata fields must be nonblank")
        return result


class ProfileSubmission(_Output):
    items: list[ProfileClaim] = Field(max_length=20)
    metadata_updates: list[ProfileMetadataPatch] = Field(default_factory=list, max_length=20)
    reason: str = Field(default="", max_length=2000)
