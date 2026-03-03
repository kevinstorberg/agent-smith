"""Shared filesystem utilities for sync scripts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def collect_md_files(sources: list[str], harness_root: Path) -> list[Path]:
    """
    Gather *.md files from a list of source paths (files or directories).
    Files are included directly; directories yield their *.md children, sorted lexicographically.
    Skips hidden files (dot-prefixed).
    """
    files: list[Path] = []
    for source in sources:
        path = (harness_root / source).expanduser().resolve()
        if path.is_file() and path.suffix == ".md":
            files.append(path)
        elif path.is_dir():
            files.extend(
                sorted(f for f in path.glob("*.md") if not f.name.startswith("."))
            )
    return files


def extract_brief(content: str, rules_path: Path) -> str:
    """
    Return Rule + Action + a pointer line for a rule file.
    If no '* **Your Process:**' marker exists, returns content unchanged
    (handles files like execution_constraints.md that have no process loop).
    """
    marker = "* **Your Process:**"
    if marker not in content:
        return content
    before = content.split(marker)[0].rstrip()
    return f"{before}\n* **Your Process:** See `{rules_path}`\n"


def atomic_write(path: Path | str, content: str) -> tuple[bool, str]:
    """Write file atomically; skips write if content is unchanged."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False, f"unchanged: {path}"

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    os.replace(str(tmp_path), str(path))
    return True, f"updated:   {path}"
