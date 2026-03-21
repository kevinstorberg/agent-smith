"""Centralized repo root and sys.path bootstrapping."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.resolve()


def ensure_importable() -> Path:
    """Add repo root to sys.path if not already present. Returns REPO_ROOT."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    return REPO_ROOT
