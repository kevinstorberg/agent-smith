from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from datetime import timedelta
from pathlib import Path

from services.costs.aws import fetch_aws, month_window
from services.costs.cache import SnapshotCache
from services.costs.pinecone_usage import PriceBook, build_usage
from services.costs.contracts import require_utc


def _enabled(name: str, values=None) -> bool:
    value = (os.environ if values is None else values).get(name, "false").lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError(f"{name} must be true or false")
    return value in {"true", "1"}


def cache_directory(values=None) -> Path:
    from services.config import APP_ENV

    configured = (os.environ if values is None else values).get("COSTS_CACHE_PATH")
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


@dataclass(frozen=True)
class PineconeConfiguration:
    project_id: str
    api_key: str = field(repr=False)
    prices: PriceBook | None
    minimum: Decimal


def _pinecone_operation(now, operation):
    now = require_utc(now or datetime.now(timezone.utc))
    values = dict(os.environ)
    try:
        if not _enabled("PINECONE_COSTS_ENABLED", values):
            return {
                "state": "disabled",
                "report": None,
                "error": None,
                "message": "Enable PINECONE_COSTS_ENABLED=true and configure PINECONE_PROJECT_ID and PINECONE_API_KEY to observe usage going forward.",
            }
        project = values.get("PINECONE_PROJECT_ID", "")
        key = values.get("PINECONE_API_KEY", "")
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", project)
            or not key
            or key != key.strip()
            or len(key) > 4096
            or any(ord(character) < 32 for character in key)
        ):
            raise ValueError(
                "Configure a valid PINECONE_PROJECT_ID and PINECONE_API_KEY."
            )
        prices = PriceBook.from_env(values, now)
        try:
            minimum = Decimal(values.get("PINECONE_COSTS_MONTHLY_MINIMUM_USD", "50"))
        except InvalidOperation:
            raise ValueError(
                "PINECONE_COSTS_MONTHLY_MINIMUM_USD must be a finite nonnegative amount."
            ) from None
        if not minimum.is_finite() or minimum < 0:
            raise ValueError(
                "PINECONE_COSTS_MONTHLY_MINIMUM_USD must be a finite nonnegative amount."
            )
        config = PineconeConfiguration(project, key, prices, minimum)
        from services.config import APP_ENV

        cache = SnapshotCache(
            cache_directory(values),
            "pinecone",
            f"{APP_ENV}:project:{project}",
            success_interval=timedelta(minutes=5),
            failure_interval=timedelta(minutes=5),
            daily_attempt_limit=288,
        )
        return operation(config, cache, now)
    except (ValueError, OSError) as error:
        return {
            "state": "not_configured",
            "report": None,
            "error": {
                "code": "configuration_error",
                "message": str(error)
                if isinstance(error, ValueError)
                else "Check COSTS_CACHE_PATH access for Pinecone snapshots.",
            },
        }


def read_pinecone_costs(now: datetime | None = None) -> dict:
    def read(config, cache, at):
        view = cache.read()
        if view["report"] and view["report"]["period_start"] != month_window(at)[0]:
            return {
                "state": "pending",
                "report": None,
                "error": None,
                "message": "A current-month baseline has not been collected; historical usage is unavailable.",
            }
        if (
            view["report"]
            and view.get("next_refresh_at")
            and at >= datetime.fromisoformat(view["next_refresh_at"])
        ):
            view["state"] = "stale"
            if not view.get("error"):
                view["message"] = (
                    "The Pinecone collector update is overdue; the last observed snapshot is retained."
                )
        return view

    return _pinecone_operation(now, read)


def collect_pinecone_costs(now: datetime | None = None) -> dict:
    def collect(config, cache, at):
        from services.costs import pinecone_metrics
        from services.observability import trigger_context

        def provider(previous_report, state):
            with trigger_context(
                trigger="costs.collector", source="costs", reason="scheduled_metrics"
            ):
                sample = pinecone_metrics.collect_metrics(
                    config.project_id, config.api_key
                )
                collected_at = now or datetime.now(timezone.utc)
                return build_usage(
                    collected_at, sample, state, config.prices, config.minimum
                )

        return cache.read_or_collect(at, provider)

    return _pinecone_operation(now, collect)
