from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from scripts.shared.validation import (
    MAX_NAME_LENGTH, validate_item_name, validate_repo_format, validate_agents_list,
)
from services.config import ALL_AGENTS


def _make_optional(fn):
    return lambda v: fn(v) if v is not None else v


def _check_name(v: str) -> str:
    return validate_item_name(v)


_check_name_optional = _make_optional(_check_name)


def _check_content(v: dict) -> dict:
    if "body" not in v or not isinstance(v["body"], str):
        raise ValueError("content must have a 'body' key with a string value")
    return v


def _check_agents(v: list[str]) -> list[str]:
    return validate_agents_list(v, ALL_AGENTS)


_check_agents_optional = _make_optional(_check_agents)


def _check_repo(v: str) -> str:
    return validate_repo_format(v)


_check_repo_optional = _make_optional(_check_repo)


class CreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    content: dict
    project: str | None = None
    agents: list[str] = []
    sort_key: int | None = None
    enabled: bool = True
    device: str = "*"
    repo: str = "*"

    _val_name = field_validator("name")(_check_name)
    _val_content = field_validator("content")(_check_content)
    _val_agents = field_validator("agents")(_check_agents)
    _val_repo = field_validator("repo")(_check_repo)


class ContentUpdate(BaseModel):
    content: dict

    _val_content = field_validator("content")(_check_content)


class MetadataUpdate(BaseModel):
    enabled: bool | None = None
    agents: list[str] | None = None
    name: str | None = Field(None, min_length=1, max_length=MAX_NAME_LENGTH)
    sort_key: int | None = None
    project: str | None = None
    clone_as_skill: bool | None = None

    _val_name = field_validator("name")(_check_name_optional)
    _val_agents = field_validator("agents")(_check_agents_optional)


class ReorderRequest(BaseModel):
    ids: list[int]

    @field_validator("ids")
    @classmethod
    def ids_must_be_valid(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("ids must not be empty")
        if any(i <= 0 for i in v):
            raise ValueError("all ids must be positive")
        return v


class ConfigCreate(BaseModel):
    device: str = "*"
    repo: str = "*"
    agents: list[str] = ["claude", "codex", "gemini"]
    subagents: list[str] = []
    enabled: bool = True
    exclude: bool = False

    _val_repo = field_validator("repo")(_check_repo)
    _val_agents = field_validator("agents")(_check_agents)


class ConfigUpdate(BaseModel):
    device: str | None = None
    repo: str | None = None
    agents: list[str] | None = None
    subagents: list[str] | None = None
    enabled: bool | None = None
    exclude: bool | None = None

    _val_repo = field_validator("repo")(_check_repo_optional)
    _val_agents = field_validator("agents")(_check_agents_optional)
