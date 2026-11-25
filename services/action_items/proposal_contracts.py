from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.action_items.contracts import Contract, Create, Patch, PositiveInt
from services.action_items.queue_contracts import EpicReference
from services.meetings.outputs import Evidence

TASK_FIELDS = frozenset({"title", "description", "project", "tags", "status", "due_at"})
MAX_CONTEXT_ITEMS = 200


class ActionItemContextTooLarge(ValueError):
    pass


class ProposalPlacement(Contract):
    expected_parent: EpicReference | None = None
    destination: EpicReference


class ProposalApprove(Contract):
    placement: ProposalPlacement | None = None
    complete: bool = False


class ActionItemCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["create", "update"]
    target_id: PositiveInt | None = None
    expected_revision: PositiveInt | None = None
    changes: dict = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence: list[Evidence] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def task_contract(self):
        if set(self.changes) - TASK_FIELDS:
            raise ValueError("Proposals may change only supported task fields")
        if not self.rationale.strip():
            raise ValueError("Proposal rationale must be nonblank")
        if self.action == "create":
            if self.target_id is not None or self.expected_revision is not None:
                raise ValueError("A new task cannot identify an existing target")
            parsed = Create.model_validate(self.changes)
        else:
            if self.target_id is None or self.expected_revision is None:
                raise ValueError(
                    "An update requires a target ID and its reviewed revision"
                )
            parsed = Patch.model_validate(
                {**self.changes, "expected_revision": self.expected_revision}
            )
        self.changes = parsed.model_dump(
            mode="json", exclude_unset=True, exclude={"expected_revision", "request_id"}
        )
        return self
