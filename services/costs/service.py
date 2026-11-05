from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from datetime import timedelta
from pathlib import Path

from services.costs.aws import fetch_aws, month_window, prepare_aws
from services.costs.cache import SnapshotCache
from services.costs.pinecone_pricing import (
    STANDARD_MONTHLY_MINIMUM_USD,
    optional_setting,
)
from services.costs.pinecone_usage import PriceBook, build_usage, resolve_price_book
from services.costs.contracts import (
    CostReport,
    ProviderFailure,
    require_utc,
    valid_aws_account,
)


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
        now = require_utc(now)
        values = dict(os.environ)
        if not _enabled("AWS_COSTS_ENABLED", values):
            return {
                "state": "disabled",
                "report": None,
                "error": None,
                "message": "Enable AWS_COSTS_ENABLED=true and configure read-only AWS billing credentials; Cost Explorer charges $0.01 per API page.",
            }
        expected = values.get("AWS_COSTS_ACCOUNT_ID", "")
        if not valid_aws_account(expected):
            raise ProviderFailure(
                "not_configured",
                "Set AWS_COSTS_ACCOUNT_ID to the verified application account's 12-digit ID before enabling billing reads.",
            )
        profile = values.get("AWS_COSTS_PROFILE") or None
        if profile is not None and (
            len(profile) > 256 or any(ord(character) < 32 for character in profile)
        ):
            raise ValueError("AWS_COSTS_PROFILE must be a valid AWS profile name")
        prepared = prepare_aws(profile, expected_account=expected)
        scope = f"account-v1:{prepared.account_id}:target:{expected}:{prepared.profile_name or 'default-chain'}:{values.get('AWS_CONFIG_FILE', '')}:{values.get('AWS_SHARED_CREDENTIALS_FILE', '')}:{month_window(now)[0]}"
        cache = SnapshotCache(cache_directory(values), "aws", scope)

        def validate(report: dict | None) -> None:
            if report is not None and report.get("account_id") != expected:
                raise ProviderFailure(
                    "invalid_snapshot",
                    "AWS cost snapshot account does not match the verified application account; the report was not displayed.",
                )

        def collect() -> CostReport:
            report = fetch_aws(now, profile, prepared=prepared)
            validate(report.model_dump(mode="json"))
            return report

        validate(cache.read()["report"])
        result = cache.read_or_refresh(now, collect)
        validate(result["report"])
        return result
    except ProviderFailure as error:
        return {
            "state": "not_configured"
            if error.code in {"not_configured", "account_mismatch"}
            else "failed",
            "report": None,
            "error": {"code": error.code, "message": error.message},
        }
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
    pricing_note: str | None = None


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
        project = optional_setting(values.get("PINECONE_PROJECT_ID")) or ""
        key = optional_setting(values.get("PINECONE_API_KEY")) or ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", project):
            raise ValueError(
                "Set PINECONE_PROJECT_ID to the existing project's ID for monitoring."
            )
        if (
            not key
            or key != key.strip()
            or len(key) > 4096
            or any(ord(character) < 32 for character in key)
        ):
            raise ValueError(
                "Configure a valid server-side PINECONE_API_KEY for the project."
            )
        pricing = resolve_price_book(values, now)
        try:
            minimum = Decimal(
                optional_setting(values.get("PINECONE_COSTS_MONTHLY_MINIMUM_USD"))
                or str(STANDARD_MONTHLY_MINIMUM_USD)
            )
        except InvalidOperation:
            raise ValueError(
                "PINECONE_COSTS_MONTHLY_MINIMUM_USD must be a finite nonnegative amount."
            ) from None
        if not minimum.is_finite() or minimum < 0:
            raise ValueError(
                "PINECONE_COSTS_MONTHLY_MINIMUM_USD must be a finite nonnegative amount."
            )
        config = PineconeConfiguration(
            project_id=project,
            api_key=key,
            prices=pricing.book,
            minimum=minimum,
            pricing_note=pricing.note,
        )
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
                    collected_at,
                    sample,
                    state,
                    config.prices,
                    config.minimum,
                    pricing_note=config.pricing_note,
                )

        return cache.read_or_collect(at, provider)

    return _pinecone_operation(now, collect)
