from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query as QueryParam,
    Request,
)

from services.action_items import db
from services.action_items.contracts import Create, Delete, Move, Patch, Query
from services.api.routers.shared.items import call_item as _call

router = APIRouter()


def _query(
    request: Request,
    q: str | None = None,
    status: str = "open",
    project: str | None = None,
    tags: list[str] = QueryParam(default=[]),
    sort: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> Query:
    unknown = set(request.query_params) - Query.model_fields.keys()
    if unknown:
        raise HTTPException(
            422, f"Unknown action item filters: {', '.join(sorted(unknown))}"
        )
    return _call(
        Query.model_validate,
        {
            "q": q,
            "status": status,
            "project": project,
            "tags": tags,
            "sort": sort,
            "limit": limit,
            "offset": offset,
        },
    )


@router.get("")
def list_all(query: Query = Depends(_query)):
    return _call(db.list_items, query)


@router.post("", status_code=201)
def create(body: Create):
    return _call(db.create, body)


@router.get("/{item_id}")
def get_one(item_id: int = Path(gt=0)):
    return _call(db.get, item_id)


@router.patch("/{item_id}")
def update(body: Patch, item_id: int = Path(gt=0)):
    return _call(db.update, item_id, body)


@router.delete("/{item_id}")
def delete(body: Delete, item_id: int = Path(gt=0)):
    return _call(db.delete, item_id, body)


@router.post("/{item_id}/move")
def move(body: Move, item_id: int = Path(gt=0)):
    return _call(db.move, item_id, body)
