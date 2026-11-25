from __future__ import annotations

from collections.abc import Callable
from typing import ParamSpec, TypeVar

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.memory.db import search_page, list_page, get, update, delete
from services.memory.catalog import Conflict, NoWritePerformed, Unavailable
from services.api.routers.base import (
    require_found,
    list_response,
    delete_response,
    empty_to_none,
    query_result,
)

router = APIRouter()
_P = ParamSpec("_P")
_R = TypeVar("_R")


SORT_PATTERN = r"^(|relevance|created_at_(asc|desc)|updated_at_(asc|desc))$"
LIST_SORT_PATTERN = r"^(|created_at_(asc|desc)|updated_at_(asc|desc))$"


def _memory_result(
    operation: Callable[_P, _R], *args: _P.args, **kwargs: _P.kwargs
) -> _R:
    try:
        return query_result(operation, *args, **kwargs)
    except NoWritePerformed as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except Conflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except Unavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from None


@router.get("/search")
def search_memories(
    q: str = Query(..., min_length=1),
    repo: str = Query(""),
    tags: list[str] = Query(default_factory=list, max_length=20),
    sort: str = Query("", pattern=SORT_PATTERN),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    meeting_only: bool = False,
):
    items, total = _memory_result(
        search_page,
        q,
        repo=empty_to_none(repo),
        tags=tags or None,
        sort=sort or None,
        limit=limit,
        offset=offset,
        meeting_only=meeting_only,
    )
    return list_response(items, total)


@router.get("/list")
def list_all(
    repo: str = Query(""),
    tags: list[str] = Query(default_factory=list, max_length=20),
    sort: str = Query("", pattern=LIST_SORT_PATTERN),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    meeting_only: bool = False,
):
    items, total = _memory_result(
        list_page,
        repo=empty_to_none(repo),
        tags=tags or None,
        sort=sort or "created_at_desc",
        limit=limit,
        offset=offset,
        meeting_only=meeting_only,
    )
    return list_response(items, total)


@router.get("/{memory_id}")
def get_memory(memory_id: str):
    return require_found(get(memory_id), "Memory", memory_id)


class MemoryUpdate(BaseModel):
    content: str | None = None
    repo: str | None = None
    tags: list[str] | None = None


@router.put("/{memory_id}")
def update_memory(memory_id: str, body: MemoryUpdate):
    _memory_result(
        update,
        memory_id,
        content=body.content,
        repo=body.repo,
        tags=body.tags,
    )
    return require_found(get(memory_id, record_access=False), "Memory", memory_id)


@router.delete("/{memory_id}")
def delete_memory(memory_id: str):
    require_found(get(memory_id, record_access=False), "Memory", memory_id)
    _memory_result(delete, memory_id)
    return delete_response(memory_id)
