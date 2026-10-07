from __future__ import annotations

import os
import re
from pathlib import Path


def read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid environment assignment in {path.name}: {key}")
        values[key] = val
    return values


def environment(harness_root: Path, app_env: str, inherited: dict[str, str] | None = None) -> dict[str, str]:
    if app_env not in {"development", "test", "production"}:
        raise ValueError("APP_ENV must be development, test, or production")
    overrides = read_env_file(harness_root / f".env.{app_env}")
    inherited = dict(os.environ if inherited is None else inherited)
    defaults = read_env_file(harness_root / ".env.default")
    result = {**defaults, **overrides, **inherited, "APP_ENV": app_env}
    if app_env == "development" and "DASHBOARD_PORT" not in overrides and "DASHBOARD_PORT" not in inherited:
        result["DASHBOARD_PORT"] = "7655"
    result.setdefault("MEMORY_STORE_PATH", str(harness_root / "memory_store" / app_env))
    return result


def _load_env_file(path: Path, override: bool = False) -> None:
    for key, value in read_env_file(path).items():
        if override or key not in os.environ:
            os.environ[key] = value


def load_dotenv(harness_root: Path) -> None:
    app_env = os.environ.get("APP_ENV", "development")
    os.environ.update(environment(harness_root, app_env))


ENV_REFERENCE = re.compile(r"\$\{(\w+)\}")


def env_references(value) -> set[str]:
    """Names of the ${VAR} tokens anywhere in a string, dict or list."""
    if isinstance(value, str):
        return set(ENV_REFERENCE.findall(value))
    if isinstance(value, dict):
        return set().union(*(env_references(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(env_references(v) for v in value))
    return set()


def expand_env(value, extra=None):
    """Substitute ${VAR} tokens from the environment, recursing into dicts/lists.

    ``extra`` supplies extra substitutions (e.g. a sync-time ${REPO_ROOT}) that take
    precedence over os.environ. Unknown tokens are left untouched.
    """
    lookup = {**os.environ, **(extra or {})}
    if isinstance(value, str):
        return ENV_REFERENCE.sub(lambda m: lookup.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {k: expand_env(v, extra) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v, extra) for v in value]
    return value
