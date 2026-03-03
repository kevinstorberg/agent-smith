#!/usr/bin/env python3
"""
sync.py

Copy harness/main.md into:
  - ~/.claude/CLAUDE.md
  - ~/.codex/AGENTS.md
  - ~/.gemini/GEMINI.md   (Gemini CLI global context)

Nothing more.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from typing import Tuple


def find_harness_dir(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not (p / "main.md").is_file():
            raise FileNotFoundError(f"harness dir missing main.md: {p}")
        return p

    # Search upward from this script for harness/main.md
    here = Path(__file__).resolve().parent
    for base in [here, *here.parents]:
        candidate = base / "harness"
        if (candidate / "main.md").is_file():
            return candidate

    raise FileNotFoundError(
        "Could not locate harness/main.md. Run from your repo or pass --harness-dir."
    )


def atomic_write(path: Path, content: str) -> Tuple[bool, str]:
    """Write file atomically only if content changed."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing == content:
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


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sync.py",
        description="Copy harness/main.md to Claude, Codex, and Gemini CLI home instruction files",
    )
    parser.add_argument(
        "--harness-dir",
        default=None,
        help="Path to harness/ (defaults to searching upward for harness/main.md)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without writing files",
    )
    args = parser.parse_args()

    harness_dir = find_harness_dir(args.harness_dir)
    src = harness_dir / "main.md"
    content = src.read_text(encoding="utf-8").rstrip() + "\n"

    claude_target = Path.home() / ".claude" / "CLAUDE.md"
    codex_target = Path.home() / ".codex" / "AGENTS.md"
    gemini_target = Path.home() / ".gemini" / "GEMINI.md"

    if args.dry_run:
        print(f"source:    {src}")
        print(f"would write {len(content.encode('utf-8'))} bytes to:")
        print(f"  {claude_target}")
        print(f"  {codex_target}")
        print(f"  {gemini_target}")
        return 0

    print(f"source:    {src}")
    print(atomic_write(claude_target, content)[1])
    print(atomic_write(codex_target, content)[1])
    print(atomic_write(gemini_target, content)[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())