from __future__ import annotations

from datetime import date

METADATA_FIELDS = {"gender", "marital_status", "company", "job_role", "start_date", "supervisor", "other"}
METADATA_CHOICES = {
    "gender": ("Male", "Female", "Non-binary", "Other"),
    "marital_status": ("Single", "Married", "Divorced", "Separated", "Widowed", "Domestic partnership", "Other"),
}
SECTION_FIELDS = {"overview", "drivers", "strengths", "development_areas", "working_style", "relationships"}
MAX_NOTE_LENGTH = 4000


def normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def text(value: str, field: str, limit: int = MAX_NOTE_LENGTH) -> str:
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise ValueError(f"{field} must be text of at most {limit} characters")
    return value.strip()


def fields(value: dict, allowed: set[str], field: str, *, existing: dict | None = None) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError(f"{field} contains unsupported fields")
    normalized = {key: text(item, f"{field}.{key}") for key, item in value.items()}
    if field == "metadata":
        for key, choices in METADATA_CHOICES.items():
            if not normalized.get(key):
                continue
            if existing is not None and value[key] == existing.get(key):
                normalized[key] = value[key]
                continue
            matched = next((choice for choice in choices if normalized_text(choice) == normalized_text(normalized[key])), None)
            if matched is None:
                raise ValueError(f"Profile {key} must be one of: {', '.join(choices)}; use empty text to clear it")
            normalized[key] = matched
    if normalized.get("start_date"):
        try:
            parsed = date.fromisoformat(normalized["start_date"])
        except ValueError:
            raise ValueError("Profile start_date must use YYYY-MM-DD") from None
        if parsed.isoformat() != normalized["start_date"]:
            raise ValueError("Profile start_date must use YYYY-MM-DD")
    return normalized


def patch(existing: dict, changes: dict) -> dict:
    return {key: value for key, value in {**existing, **changes}.items() if value}


def nicknames(values: list[str]) -> list[str]:
    if not isinstance(values, list) or len(values) > 20:
        raise ValueError("Provide at most 20 nicknames")
    result, seen = [], set()
    for value in values:
        name = text(value, "Nickname", 100)
        if not name:
            raise ValueError("Nicknames must be nonblank")
        if name.casefold() not in seen:
            result.append(name)
            seen.add(name.casefold())
    return result
