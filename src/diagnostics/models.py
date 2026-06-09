from typing import Any, Literal

from pydantic import BaseModel, Field

DiagnosticStatus = Literal["pass", "warn", "fail"]


class DiagnosticResult(BaseModel):
    name: str
    status: DiagnosticStatus
    details: dict[str, Any] = Field(default_factory=dict)


class DiagnosticReport(BaseModel):
    results: list[DiagnosticResult]
