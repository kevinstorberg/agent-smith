from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.memory.db import search, list_memories, get, update, delete

router = APIRouter()


@router.get("/search")
def search_memories(
    q: str = Query(..., min_length=1),
    repo: str = Query(""),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    all_results = search(q, repo=repo or None, limit=limit + offset)
    items = all_results[offset:offset + limit]
    return {"items": items, "total": len(all_results)}


@router.get("/list")
def list_all(
    repo: str = Query(""),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    all_results = list_memories(repo=repo or None, limit=limit + offset + 100)
    total = len(all_results)
    items = all_results[offset:offset + limit]
    return {"items": items, "total": total}


@router.get("/{memory_id}")
def get_memory(memory_id: str):
    item = get(memory_id)
    if not item:
        raise HTTPException(404, "Memory not found")
    return item


class MemoryUpdate(BaseModel):
    content: str | None = None
    repo: str | None = None
    tags: list[str] | None = None


@router.put("/{memory_id}")
def update_memory(memory_id: str, body: MemoryUpdate):
    existing = get(memory_id)
    if not existing:
        raise HTTPException(404, "Memory not found")
    update(
        memory_id,
        content=body.content,
        repo=body.repo,
        tags=body.tags,
    )
    return get(memory_id)


@router.delete("/{memory_id}")
def delete_memory(memory_id: str):
    existing = get(memory_id)
    if not existing:
        raise HTTPException(404, "Memory not found")
    delete(memory_id)
    return {"deleted": True, "id": memory_id}
