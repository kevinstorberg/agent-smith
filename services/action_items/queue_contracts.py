from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from services.action_items.contracts import Contract, Delete, PositiveInt, Title

Cohort = Annotated[str, Field(pattern=r"^v1:[0-9a-f]{64}$")]


class EpicReference(Delete):
    id: PositiveInt
    cohort: Cohort


class Membership(Contract):
    expected_revision: PositiveInt
    expected_parent: EpicReference | None = None
    destination: EpicReference | None = None


class EpicTitle(Contract):
    title: Title

    @field_validator("title")
    @classmethod
    def reject_nul(cls, value):
        if "\0" in value:
            raise ValueError("Epic title cannot contain NUL characters")
        return value


class EpicCreate(EpicTitle):
    request_id: str
    item_id: PositiveInt | None = None
    membership: Membership | None = None

    @field_validator("request_id")
    @classmethod
    def normalize_request(cls, value: str) -> str:
        return str(UUID(value))

    @model_validator(mode="after")
    def require_initial_item(self):
        if (self.item_id is None) != (self.membership is None):
            raise ValueError("Provide both item_id and membership for inline creation")
        if self.membership is not None and self.membership.destination is not None:
            raise ValueError("Inline creation cannot select an existing destination")
        return self


class EpicPatch(EpicTitle, Delete):
    pass


class EpicRemove(Delete):
    cohort: Cohort


class EntryReference(Delete):
    kind: Literal["item", "epic"]
    id: PositiveInt
    cohort: Cohort | None = None

    @model_validator(mode="after")
    def require_epic_cohort(self):
        if (self.kind == "epic") != (self.cohort is not None):
            raise ValueError("Only Epic references require a cohort")
        return self


class QueueMove(Contract):
    source: EntryReference
    parent: EpicReference | None = None
    before: EntryReference | None = None
    after: EntryReference | None = None

    @model_validator(mode="after")
    def exactly_one_anchor(self):
        if (self.before is None) == (self.after is None):
            raise ValueError("Provide exactly one before or after anchor")
        anchor = self.before or self.after
        if self.source.kind == anchor.kind and self.source.id == anchor.id:
            raise ValueError("Source and anchor must differ")
        if self.parent is not None and (
            self.source.kind != "item" or anchor.kind != "item"
        ):
            raise ValueError("Only Action Items may be reordered within an Epic")
        return self
