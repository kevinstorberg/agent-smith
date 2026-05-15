from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from services.memory.db import search, list_memories, get, update, delete
from services.api.routers.base import require_found, list_response, delete_response, empty_to_none, paginate

router = APIRouter()


SORT_PATTERN = r"^(|relevance|created_at_(asc|desc)|updated_at_(asc|desc))$"


@router.get("/search")
def search_memories(
    q: str = Query(..., min_length=1),
    repo: str = Query(""),
    tags: list[str] = Query(default_factory=list, max_length=20),
    sort: str = Query("", pattern=SORT_PATTERN),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    all_results = search(q, repo=empty_to_none(repo), tags=tags or None, sort=sort or None)
    items, total = paginate(all_results, offset, limit)
    return list_response(items, total)


@router.get("/list")
def list_all(
    repo: str = Query(""),
    tags: list[str] = Query(default_factory=list, max_length=20),
    sort: str = Query("", pattern=SORT_PATTERN),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    all_results = list_memories(
        repo=empty_to_none(repo),
        tags=tags or None,
        sort=sort or "created_at_desc",
    )
    items, total = paginate(all_results, offset, limit)
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
    update(
        memory_id,
        content=body.content,
        repo=body.repo,
        tags=body.tags,
    )
    return require_found(get(memory_id), "Memory", memory_id)


@router.delete("/{memory_id}")
def delete_memory(memory_id: str):
    require_found(get(memory_id), "Memory", memory_id)
    delete(memory_id)
    return delete_response(memory_id)
