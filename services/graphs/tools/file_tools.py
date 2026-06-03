"""Shared filesystem tools that any graph can import."""
from __future__ import annotations

import os

from langchain_core.tools import tool


@tool
def read_file(path: str) -> str:
    """Read the contents of a text file at `path` and return them as a string."""
    assert isinstance(path, str) and path, "read_file: path must be a non-empty string"
    with open(path, encoding="utf-8") as f:
        return f.read()


@tool
def list_dir(path: str) -> list[str]:
    """List the entries (files and subdirectories) under `path`."""
    assert isinstance(path, str) and path, "list_dir: path must be a non-empty string"
    return sorted(os.listdir(path))
