from __future__ import annotations

import os
import re
from pathlib import Path


def _load_env_file(path: Path, override: bool = False) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key and (override or key not in os.environ):
            os.environ[key] = val


def load_dotenv(harness_root: Path) -> None:
    app_env = os.environ.get("APP_ENV", "development")
    _load_env_file(harness_root / ".env.default")
    _load_env_file(harness_root / f".env.{app_env}", override=True)


def expand_env(value):
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
