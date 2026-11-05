from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path

from services.costs.aws import fetch_aws, month_window
from services.costs.cache import SnapshotCache


def _enabled(name: str) -> bool:
    value = os.environ.get(name, "false").lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError(f"{name} must be true or false")
    return value in {"true", "1"}


def cache_directory() -> Path:
    from services.config import APP_ENV

    configured = os.environ.get("COSTS_CACHE_PATH")
    path = (
        Path(configured)
        if configured
        else Path(__file__).resolve().parents[2] / ".runtime" / "costs" / APP_ENV
    )
    if not path.is_absolute():
        raise ValueError("COSTS_CACHE_PATH must be an absolute path")
    return path


def read_aws_costs(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    try:
        if not _enabled("AWS_COSTS_ENABLED"):
            return {
                "state": "disabled",
                "report": None,
                "error": None,
                "message": "Enable AWS_COSTS_ENABLED=true and configure read-only AWS billing credentials; Cost Explorer charges $0.01 per API page.",
            }
        profile = (
            os.environ.get("AWS_COSTS_PROFILE") or os.environ.get("AWS_PROFILE") or None
        )
        if profile is not None and (
            len(profile) > 256 or any(ord(character) < 32 for character in profile)
        ):
            raise ValueError("AWS_COSTS_PROFILE must be a valid AWS profile name")
        scope = f"{profile or 'default-chain'}:{os.environ.get('AWS_CONFIG_FILE', '')}:{os.environ.get('AWS_SHARED_CREDENTIALS_FILE', '')}:{month_window(now)[0]}"
        return SnapshotCache(cache_directory(), "aws", scope).read_or_refresh(
            now, lambda: fetch_aws(now, profile)
        )
    except (ValueError, OSError):
        return {
            "state": "not_configured",
            "report": None,
            "error": {
                "code": "configuration_error",
                "message": "Check cost cache access, AWS_COSTS_PROFILE and AWS_COSTS_ENABLED (true or false).",
            },
        }
