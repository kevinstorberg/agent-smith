from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.resolve()


def ensure_importable() -> Path:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    return REPO_ROOT


def bootstrap() -> Path:
    """Add repo root to sys.path and load .env files. Call once at entrypoint."""
    ensure_importable()
    from scripts.shared.env import load_dotenv
    load_dotenv(REPO_ROOT)
    return REPO_ROOT
