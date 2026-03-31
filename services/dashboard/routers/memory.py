from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from services.memory.db import search, list_memories, get, update, delete
from services.dashboard.routers.base import require_found, list_response, delete_response, empty_to_none

router = APIRouter()


@router.get("/search")
def search_memories(
    q: str = Query(..., min_length=1),
    repo: str = Query(""),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    all_results = search(q, repo=empty_to_none(repo), limit=limit + offset)
    items = all_results[offset:offset + limit]
    return list_response(items, len(all_results))


@router.get("/list")
def list_all(
    repo: str = Query(""),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    all_results = list_memories(repo=empty_to_none(repo), limit=limit + offset + 100)
    items = all_results[offset:offset + limit]
    return list_response(items, len(all_results))


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
