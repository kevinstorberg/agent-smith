from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


def search_pattern(query: str | None, *, max_length: int = 1000) -> str | None:
    if query is None or query == "":
        return None
    if not isinstance(query, str) or len(query) > max_length:
        raise ValueError(f"Search must be text of at most {max_length} characters")
    query = query.strip()
    if not query:
        return None
    return (
        "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    )


def sort_clause(sort: str, options: Mapping[str, str]) -> str:
    if not isinstance(sort, str) or sort not in options:
        raise ValueError(f"Sort must be one of: {', '.join(options)}")
    return options[sort]


def sort_pattern(options: Mapping[str, str]) -> str:
    return "^(?:" + "|".join(re.escape(key) for key in options) + ")$"


def bidirectional_sorts(
    columns: Mapping[tuple[str, str], Sequence[str]], *, tie_breaker: str = "id"
) -> dict[str, str]:
    if not isinstance(columns, Mapping) or not columns:
        raise ValueError("Sort columns must be a nonempty mapping")
    if not isinstance(tie_breaker, str) or not tie_breaker.strip():
        raise ValueError("Sort tie_breaker must be a trusted unique SQL expression")
    orders = {}
    for tokens, expressions in columns.items():
        if (
            not isinstance(tokens, tuple)
            or len(tokens) != 2
            or any(not isinstance(token, str) or not token.strip() for token in tokens)
        ):
            raise ValueError(
                "Each sort column requires ascending and descending tokens"
            )
        if tokens[0] == tokens[1] or any(token in orders for token in tokens):
            raise ValueError("Sort tokens must be unique")
        if (
            not isinstance(expressions, Sequence)
            or isinstance(expressions, (str, bytes))
            or not expressions
            or any(
                not isinstance(term, str) or not term.strip() for term in expressions
            )
        ):
            raise ValueError(
                "Sort columns require nonempty trusted SQL expression sequences"
            )
        for token, direction in zip(tokens, ("ASC", "DESC")):
            terms = [f"{term} {direction} NULLS LAST" for term in expressions]
            orders[token] = ", ".join([*terms, f"{tie_breaker} {direction}"])
    return orders
