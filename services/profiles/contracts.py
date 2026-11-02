from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, Field, StringConstraints, field_validator

from services.action_items.contracts import Contract, Delete, ItemCreate, ItemPatch, ItemQuery, Move, PositiveInt


def _profile_id(value: str) -> str:
    return str(UUID(value))


ProfileId = Annotated[str, StringConstraints(strict=True), AfterValidator(_profile_id),
                      Field(json_schema_extra={"format": "uuid"})]


class ProfileScope(Contract):
    profile_id: ProfileId


class ProfileQuery(Contract):
    q: Annotated[str, Field(max_length=1000)] | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 10
    offset: Annotated[int, Field(ge=0)] = 0

    nonblank_query = field_validator("q")(ItemQuery.nonblank_query.__func__)


class TopicList(ProfileScope, ItemQuery):
    pass


class TopicGet(ProfileScope):
    item_id: PositiveInt


class TopicCreate(ProfileScope, ItemCreate):
    pass


class TopicUpdate(TopicGet):
    changes: ItemPatch


class TopicDelete(TopicGet, Delete):
    pass


class TopicMove(TopicGet, Move):
    pass
