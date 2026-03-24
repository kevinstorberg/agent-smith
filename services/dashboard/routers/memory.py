from __future__ import annotations

from fastapi import APIRouter, Query

from services.memory.db import search, list_memories

router = APIRouter()


@router.get("/search")
def search_memories(
    q: str = Query(..., min_length=1),
    repo: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
):
    results = search(q, repo=repo or None, limit=limit)
    return results


@router.get("/list")
def list_all(
    repo: str = Query(""),
    limit: int = Query(20, ge=1, le=100),
):
    results = list_memories(repo=repo or None, limit=limit)
    return results
