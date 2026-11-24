from __future__ import annotations


def filter_decision(
    data: dict,
    index: int = 0,
    *,
    matches: list[dict] | None = None,
    actionable: bool = True,
    rationale: str = "Synthetic explicit comparison of the requested work",
) -> dict:
    matches = matches or []
    related = {match["key"] for match in matches}
    return {
        "candidate_id": index,
        "actionable": actionable,
        "matches": matches,
        "different_keys": [
            key for key in data["comparison_pairs"][str(index)] if key not in related
        ],
        "rationale": rationale,
        "evidence": data["candidates"][index]["evidence"],
    }
