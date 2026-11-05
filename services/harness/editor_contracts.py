from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from scripts.shared.agents import AGENT_TARGETS, VIRTUAL_AGENTS
from scripts.shared.validation import (
    MAX_NAME_LENGTH,
    validate_agents_list,
    validate_item_name,
    validate_repo_format,
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EditorCommon(Contract):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    project: str | None = None
    sort_key: int = Field(default=0, ge=0)
    agents: list[str]
    subagents: list[str] = Field(default_factory=list)
    enabled: bool = True
    clone_as_skill: bool = False
    device: str = Field(default="*", min_length=1, max_length=100)
    repo: str = "*"

    _name = field_validator("name")(validate_item_name)
    _repo = field_validator("repo")(validate_repo_format)

    @field_validator("agents")
    @classmethod
    def known_agents(cls, value):
        return sorted(validate_agents_list(value, [*AGENT_TARGETS, *VIRTUAL_AGENTS]))

    @field_validator("name", "project", "device", "repo")
    @classmethod
    def single_line(cls, value):
        if value is not None and any(character in value for character in "\r\n\0"):
            raise ValueError("must be a single line without control characters")
        return value or None


class EditorDraft(Contract):
    mode: Literal["guided", "raw"] = "guided"
    fields: dict = Field(default_factory=dict)
    extensions: dict = Field(default_factory=dict)
    original_content: dict | None = None
    dirty_paths: list[str] = Field(default_factory=list)
    raw: str | None = None
    source_name: str | None = None


class EditorSave(EditorDraft):
    common: EditorCommon
    expected_version: int | None = Field(default=None, ge=1)
    expected_updated_at: AwareDatetime | None = Field(default=None, strict=False)


class EditorDecode(Contract):
    name: str
    content: dict
