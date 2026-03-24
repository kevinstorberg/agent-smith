from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.resolve()


def _resolve_root(caller_file: str) -> Path:
    candidate = Path(caller_file).resolve().parent
    for _ in range(10):
        if (candidate / "scripts" / "shared" / "paths.py").exists():
            return candidate
        candidate = candidate.parent
    return REPO_ROOT


def ensure_importable(caller_file: str | None = None) -> Path:
    root = _resolve_root(caller_file) if caller_file else REPO_ROOT
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def bootstrap(caller_file: str | None = None) -> Path:
    root = ensure_importable(caller_file)
    from scripts.shared.env import load_dotenv
    load_dotenv(root)
    return root
