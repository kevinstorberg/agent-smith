from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class CostReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["aws", "pinecone"]
    period_start: date
    period_end: date
    currency: str
    total: str | None
    estimated: bool
    scope: str
    fetched_at: AwareDatetime
    daily: list[dict[str, str]] = Field(default_factory=list)
    breakdown: list[dict[str, str]] = Field(default_factory=list)
    usage: list[dict[str, str]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    coverage_start: AwareDatetime | None = None
    data_through: date | None = None
    cost_basis: str = "UnblendedCost"


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    cache_key: str
    next_attempt_at: AwareDatetime
    attempt_day: date
    attempts: int = Field(ge=0)
    report: CostReport | None = None
    error: dict[str, str] | None = None


class ProviderFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)


def require_utc(now: datetime) -> datetime:
    from datetime import timezone

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Cost collection requires an aware timestamp")
    return now.astimezone(timezone.utc)
