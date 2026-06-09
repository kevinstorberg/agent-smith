from dataclasses import dataclass
from typing import Any


@dataclass
class PaginatedResult:
    items: list[Any]
    total: int
    offset: int
    limit: int


def paginate(items: list, *, offset: int = 0, limit: int = 20) -> PaginatedResult:
    total = len(items)
    page = items[offset : offset + limit]
    return PaginatedResult(items=page, total=total, offset=offset, limit=limit)
