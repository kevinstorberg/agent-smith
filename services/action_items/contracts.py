from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Annotated, Literal
import unicodedata
from uuid import UUID

from pydantic import (
    BaseModel,
    AwareDatetime,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

from scripts.shared.validation import MAX_BODY_LENGTH, MAX_TITLE_LENGTH

Status = Literal["open", "completed"]
Sort = Literal["manual", "newest", "updated", "title", "completed"]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITLE_LENGTH),
]
Description = Annotated[str, StringConstraints(max_length=MAX_BODY_LENGTH)]
MAX_PROJECT_NAME_LENGTH = 200
MAX_DUE_WINDOW_HOURS = 168
Project = Annotated[str, StringConstraints(max_length=MAX_PROJECT_NAME_LENGTH)]
Tags = Annotated[list[str], Field(max_length=20)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProjectCreate(Contract):
    name: Annotated[
        str, StringConstraints(min_length=1, max_length=MAX_PROJECT_NAME_LENGTH)
    ]

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        if isinstance(value, str):
            if any(unicodedata.category(character) == "Cc" for character in value):
                raise ValueError("Project names cannot contain control characters")
            return value.strip()
        return value


class ItemEditable(Contract):
    title: Title | None = None
    description: Description | None = None
    tags: Tags | None = None
    status: Status | None = None

    @field_validator("description", mode="before")
    @classmethod
    def clear_description(cls, value):
        return "" if value is None else value

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value):
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 20:
            raise ValueError("tags must be a list of at most 20 strings")
        if any(
            not isinstance(tag, str) or not tag.strip() or len(tag.strip()) > 100
            for tag in value
        ):
            raise ValueError("each tag must contain 1-100 nonblank characters")
        return sorted({tag.strip().casefold() for tag in value})

    @model_validator(mode="after")
    def reject_required_clears(self):
        for name in ("title", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class ProjectFields(Contract):
    project: Project | None = None

    @field_validator("project")
    @classmethod
    def normalize_project(cls, value):
        if value is not None and "\0" in value:
            raise ValueError("Project cannot contain NUL characters")
        # Legacy exact names must reach catalog resolution before new-name normalization.
        return None if value == "" else value


class DueFields(Contract):
    due_at: datetime | None = Field(
        default=None,
        description="Timezone-aware deadline with microsecond precision, at most six fractional digits.",
    )

    @field_validator("due_at", mode="before")
    @classmethod
    def utc_deadline(cls, value: object) -> datetime | None:
        if value is None:
            return None
        if (
            not isinstance(value, (str, datetime))
            or isinstance(value, str)
            and "T" not in value
        ):
            raise ValueError("due_at must be an ISO datetime with an explicit timezone")
        if isinstance(value, str):
            fraction = re.search(r"[.,](\d+)", value)
            if fraction is not None and len(fraction.group(1)) > 6:
                raise ValueError("due_at supports at most six fractional second digits")
        try:
            return (
                TypeAdapter(AwareDatetime)
                .validate_python(value)
                .astimezone(timezone.utc)
            )
        except (ValueError, OverflowError) as error:
            raise ValueError(
                "due_at must be a valid timezone-aware datetime within the UTC calendar"
            ) from error


class Editable(ItemEditable, ProjectFields, DueFields):
    pass


class ItemCreate(ItemEditable):
    title: Title
    description: Description = ""
    tags: Tags = Field(default_factory=list)
    status: Status = "open"
    request_id: str | None = None

    @field_validator("request_id")
    @classmethod
    def normalize_request_id(cls, value):
        return str(UUID(value)) if value is not None else None


class Create(ItemCreate, ProjectFields, DueFields):
    pass


class ItemPatch(ItemEditable):
    expected_revision: PositiveInt


class Patch(ItemPatch, ProjectFields, DueFields):
    pass


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


class ItemQuery(Contract):
    q: Annotated[str, Field(max_length=1000)] | None = None
    status: Literal["open", "completed", "all"] = "open"
    tags: Tags = Field(default_factory=list)
    sort: Sort | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 10
    offset: Annotated[int, Field(ge=0)] = 0

    normalize_tags = field_validator("tags", mode="before")(
        ItemEditable.normalize_tags.__func__
    )

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
            raise ValueError(
                "completed sort is only available for completed action items"
            )
        return self


class Query(ItemQuery, ProjectFields):
    unassigned: bool = False
    due_within_hours: (
        Annotated[int, Field(strict=True, ge=1, le=MAX_DUE_WINDOW_HOURS)] | None
    ) = None

    @model_validator(mode="after")
    def project_scope(self):
        if self.unassigned and self.project is not None:
            raise ValueError("project and unassigned cannot be used together")
        return self
