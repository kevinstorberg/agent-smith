from __future__ import annotations

import re
from collections.abc import Mapping


def search_pattern(query: str | None, *, max_length: int = 1000) -> str | None:
    if query is None or query == "":
        return None
    if not isinstance(query, str) or len(query) > max_length:
        raise ValueError(f"Search must be text of at most {max_length} characters")
    query = query.strip()
    if not query:
        return None
    return "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def sort_clause(sort: str, options: Mapping[str, str]) -> str:
    if not isinstance(sort, str) or sort not in options:
        raise ValueError(f"Sort must be one of: {', '.join(options)}")
    return options[sort]


def sort_pattern(options: Mapping[str, str]) -> str:
    return "^(?:" + "|".join(re.escape(key) for key in options) + ")$"
