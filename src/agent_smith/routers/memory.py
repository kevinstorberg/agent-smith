from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.agent_smith.responses import delete_response, empty_to_none, list_response, paginate, require_found
from src.agent_smith.services.memory import get_memory_service

router = APIRouter()

SORT_PATTERN = r"^(|relevance|created_at_(asc|desc)|updated_at_(asc|desc))$"


class MemoryUpdate(BaseModel):
    content: str | None = None
    repo: str | None = None
    tags: list[str] | None = None


@router.get("/search")
def search_memories(
    q: str = Query(..., min_length=1),
    repo: str = Query(""),
    tags: list[str] = Query(default_factory=list, max_length=20),
    sort: str = Query("", pattern=SORT_PATTERN),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    service = get_memory_service()
    results = service.search(
        query=q,
        repo=empty_to_none(repo),
        tags=tags or None,
        sort=sort or None,
    )
    items, total = paginate(results, offset, limit)
    return list_response(items, total)


@router.get("/list")
def list_all(
    repo: str = Query(""),
    tags: list[str] = Query(default_factory=list, max_length=20),
    sort: str = Query("", pattern=SORT_PATTERN),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    service = get_memory_service()
    results = service.list_memories(
        repo=empty_to_none(repo),
        tags=tags or None,
        sort=sort or "created_at_desc",
    )
    items, total = paginate(results, offset, limit)
    return list_response(items, total)


@router.get("/{memory_id}")
def get_memory(memory_id: str):
    return require_found(get_memory_service().get(memory_id), "Memory", memory_id)


@router.put("/{memory_id}")
def update_memory(memory_id: str, body: MemoryUpdate):
    service = get_memory_service()
    service.update(
        memory_id=memory_id,
        content=body.content,
        repo=body.repo,
        tags=body.tags,
    )
    return require_found(service.get(memory_id), "Memory", memory_id)


@router.delete("/{memory_id}")
def delete_memory(memory_id: str):
    service = get_memory_service()
    require_found(service.get(memory_id), "Memory", memory_id)
    service.delete(memory_id)
    return delete_response(memory_id)
