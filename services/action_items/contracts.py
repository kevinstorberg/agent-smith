from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from scripts.shared.validation import MAX_BODY_LENGTH, MAX_TITLE_LENGTH

Status = Literal["open", "completed"]
Sort = Literal["manual", "newest", "updated", "title", "completed"]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITLE_LENGTH)]
Description = Annotated[str, StringConstraints(max_length=MAX_BODY_LENGTH)]
Project = Annotated[str, StringConstraints(max_length=200)]
Tags = Annotated[list[str], Field(max_length=20)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Editable(Contract):
    title: Title | None = None
    description: Description | None = None
    project: Project | None = None
    tags: Tags | None = None
    status: Status | None = None

    @field_validator("description", mode="before")
    @classmethod
    def clear_description(cls, value):
        return "" if value is None else value

    @field_validator("project")
    @classmethod
    def normalize_project(cls, value):
        return value.strip() or None if value is not None else None

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value):
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 20:
            raise ValueError("tags must be a list of at most 20 strings")
        if any(not isinstance(tag, str) or not tag.strip() or len(tag.strip()) > 100 for tag in value):
            raise ValueError("each tag must contain 1-100 nonblank characters")
        return sorted({tag.strip().casefold() for tag in value})

    @model_validator(mode="after")
    def reject_required_clears(self):
        for name in ("title", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class Create(Editable):
    title: Title
    description: Description = ""
    tags: Tags = Field(default_factory=list)
    status: Status = "open"
    request_id: str | None = None

    @field_validator("request_id")
    @classmethod
    def normalize_request_id(cls, value):
        return str(UUID(value)) if value is not None else None


class Patch(Editable):
    expected_revision: PositiveInt


class Delete(Contract):
    expected_revision: PositiveInt


class Move(Delete):
    before_id: PositiveInt | None = None
    after_id: PositiveInt | None = None

    @model_validator(mode="after")
    def exactly_one_anchor(self):
        if (self.before_id is None) == (self.after_id is None):
            raise ValueError("provide exactly one before_id or after_id")
        return self


class Query(Contract):
    q: Annotated[str, Field(max_length=1000)] | None = None
    status: Literal["open", "completed", "all"] = "open"
    project: Project | None = None
    tags: Tags = Field(default_factory=list)
    sort: Sort | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 10
    offset: Annotated[int, Field(ge=0)] = 0

    normalize_tags = field_validator("tags", mode="before")(Editable.normalize_tags.__func__)
    normalize_project = field_validator("project")(Editable.normalize_project.__func__)

    @field_validator("q")
    @classmethod
    def nonblank_query(cls, value):
        if value is not None and not value.strip():
            raise ValueError("q must contain nonblank text")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_sort(self):
        if self.sort == "manual" and self.status != "open":
            raise ValueError("manual sort is only available for open action items")
        if self.sort == "completed" and self.status != "completed":
            raise ValueError("completed sort is only available for completed action items")
        return self
