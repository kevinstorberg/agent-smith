from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query as QueryParam, Request

from services.action_items import db
from services.action_items.contracts import Delete, ItemCreate, ItemPatch, ItemQuery, Move
from services.api.routers.shared.items import call_item

router = APIRouter(prefix="/{profile_id}/discussion-topics")


def _query(request: Request, q: str | None = None, status: str = "open",
           tags: list[str] = QueryParam(default_factory=list), sort: str | None = None,
           limit: int = 10, offset: int = 0) -> ItemQuery:
    unknown = set(request.query_params) - ItemQuery.model_fields.keys()
    if unknown:
        raise HTTPException(422, f"Unknown discussion topic filters: {', '.join(sorted(unknown))}")
    return call_item(ItemQuery.model_validate, {"q": q, "status": status, "tags": tags, "sort": sort,
                                               "limit": limit, "offset": offset})


@router.get("")
def list_all(profile_id: UUID, query: ItemQuery = Depends(_query)):
    return call_item(db.profile_queue(str(profile_id)).list_items, query.model_dump())


@router.post("", status_code=201)
def create(profile_id: UUID, body: ItemCreate):
    return call_item(db.profile_queue(str(profile_id)).create, body.model_dump())


@router.get("/{item_id}")
def get_one(profile_id: UUID, item_id: int = Path(gt=0)):
    return call_item(db.profile_queue(str(profile_id)).get, item_id)


@router.patch("/{item_id}")
def update(profile_id: UUID, body: ItemPatch, item_id: int = Path(gt=0)):
    return call_item(db.profile_queue(str(profile_id)).update, item_id, body.model_dump(exclude_unset=True))


@router.delete("/{item_id}")
def delete(profile_id: UUID, body: Delete, item_id: int = Path(gt=0)):
    return call_item(db.profile_queue(str(profile_id)).delete, item_id, body)


@router.post("/{item_id}/move")
def move(profile_id: UUID, body: Move, item_id: int = Path(gt=0)):
    return call_item(db.profile_queue(str(profile_id)).move, item_id, body)
