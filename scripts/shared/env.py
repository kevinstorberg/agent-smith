"""Load .env file into os.environ and expand ${VAR} references."""

from __future__ import annotations

import os
import re
from pathlib import Path


def load_dotenv(harness_root: Path) -> None:
    """Load .env into os.environ if it exists. Does not override existing vars."""
    env_file = harness_root / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = val


def expand_env(value):
    """Recursively expand ${VAR} references in strings, dicts, and lists."""
    if isinstance(value, str):
        return re.sub(
            r"\$\{(\w+)\}",
            lambda m: os.environ.get(m.group(1), m.group(0)),
            value,
        )
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value
