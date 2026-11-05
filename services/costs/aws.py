from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import re
import time
from typing import Any

from services.costs.contracts import (
    CostReport,
    ProviderFailure,
    require_utc,
    valid_aws_account,
)
from services.costs.periods import month_window
from services.observability import billable_operation


def collect_aws(client, account_id: str, now: datetime) -> CostReport:
    now = require_utc(now)
    if not valid_aws_account(account_id):
        raise ProviderFailure(
            "invalid_response", "AWS returned an invalid account identity."
        )
    start, end = month_window(now)
    params = {
        "TimePeriod": {"Start": start, "End": end},
        "Granularity": "DAILY",
        "Metrics": ["UnblendedCost"],
        "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
        "Filter": {"Dimensions": {"Key": "LINKED_ACCOUNT", "Values": [account_id]}},
    }
    daily, services = defaultdict(Decimal), defaultdict(Decimal)
    currency = None
    estimated = False
    tokens = set()
    started = time.monotonic()
    try:
        for _ in range(20):
            if time.monotonic() - started > 45:
                raise ProviderFailure(
                    "timeout", "AWS cost pagination exceeded its time limit."
                )
            with billable_operation(
                "aws_cost_explorer",
                "get_cost_and_usage",
                source="costs",
                reason="cost_dashboard",
                sdk_retries=0,
            ):
                page = client.get_cost_and_usage(**params)
            results = page["ResultsByTime"]
            if not isinstance(results, list):
                raise ValueError("Invalid results")
            for result in results:
                day = date.fromisoformat(result["TimePeriod"]["Start"])
                day_end = date.fromisoformat(result["TimePeriod"]["End"])
                if not (
                    date.fromisoformat(start) <= day < date.fromisoformat(end)
                ) or day_end != day + timedelta(days=1):
                    raise ValueError("Unexpected billing period")
                if type(result["Estimated"]) is not bool:
                    raise ValueError("Missing estimate status")
                estimated |= result["Estimated"]
                groups = result.get("Groups", [])
                if not groups:
                    groups = [
                        {"Keys": ["Unspecified service"], "Metrics": result["Total"]}
                    ]
                for group in groups:
                    keys = group["Keys"]
                    if (
                        not isinstance(keys, list)
                        or len(keys) != 1
                        or not isinstance(keys[0], str)
                    ):
                        raise ValueError("Invalid service dimension")
                    metric = group["Metrics"]["UnblendedCost"]
                    unit = metric["Unit"]
                    if (
                        not isinstance(unit, str)
                        or not re.fullmatch(r"[A-Z]{3}", unit)
                        or (currency and unit != currency)
                    ):
                        raise ValueError("Unexpected currency")
                    currency = unit
                    amount = Decimal(metric["Amount"])
                    if not amount.is_finite():
                        raise ValueError("Nonfinite cost")
                    daily[day.isoformat()] += amount
                    services[keys[0] or "Unspecified service"] += amount
            token = page.get("NextPageToken")
            if not token:
                break
            if not isinstance(token, str) or token in tokens:
                raise ValueError("Invalid pagination token")
            tokens.add(token)
            params["NextPageToken"] = token
        else:
            raise ProviderFailure(
                "limit_exceeded", "AWS cost report exceeded its pagination limit."
            )
        if not daily or not currency:
            raise ProviderFailure(
                "data_unavailable",
                "AWS has not supplied cost data for this period yet.",
            )
    except ProviderFailure:
        raise
    except (KeyError, ValueError, TypeError, InvalidOperation):
        raise ProviderFailure(
            "invalid_response",
            "AWS returned an unsupported or incomplete cost response.",
        ) from None
    return CostReport(
        provider="aws",
        period_start=start,
        period_end=end,
        currency=currency,
        total=str(sum(daily.values(), Decimal(0))),
        estimated=estimated,
        scope=f"AWS account {account_id}",
        account_id=account_id,
        fetched_at=now,
        data_through=max(date.fromisoformat(day) for day in daily),
        daily=[
            {"label": key, "amount": str(value)} for key, value in sorted(daily.items())
        ],
        breakdown=[
            {"label": key, "amount": str(value)}
            for key, value in sorted(
                services.items(), key=lambda pair: pair[1], reverse=True
            )
        ],
        notes=[
            "Costs are filtered to this verified account, excluding other organization accounts; not limited to Agent Smith resources.",
            "Unblended costs include credits and refunds; they are not a final invoice.",
            "AWS data is delayed and this report is cached for 24 hours; displayed spending can lag by roughly 48 hours.",
            "Cost Explorer charges $0.01 for each API page requested.",
        ],
    )


def _require_aws_calls_allowed() -> None:
    from scripts.shared.automated_tests import automated_tests_enabled

    if automated_tests_enabled():
        raise ProviderFailure(
            "automated_test", "Live billing calls are disabled in automated tests."
        )


@contextmanager
def _aws_sdk() -> Iterator[tuple[Any, Any]]:
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        raise ProviderFailure(
            "not_configured",
            "Install the application's updated requirements to enable AWS costs.",
        ) from None
    try:
        yield boto3, Config
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        if code in {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation"}:
            raise ProviderFailure(
                "permission_denied",
                "Enable Cost Explorer and grant ce:GetCostAndUsage to the configured AWS identity.",
            ) from None
        raise ProviderFailure(
            "provider_error",
            "AWS billing access failed. Check credentials and Cost Explorer availability.",
        ) from None
    except BotoCoreError:
        raise ProviderFailure(
            "not_configured",
            "AWS billing credentials are unavailable or the connection failed.",
        ) from None


@dataclass(frozen=True)
class AwsCredentialsSnapshot:
    session: Any = field(repr=False)
    config: Any = field(repr=False)
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    session_token: str | None = field(repr=False)

    def client(self, service: str) -> Any:
        return self.session.client(
            service,
            region_name="us-east-1",
            config=self.config,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            aws_session_token=self.session_token,
        )


@dataclass(frozen=True)
class AwsIdentity:
    account_id: str
    credentials: AwsCredentialsSnapshot = field(repr=False)
    profile_name: str | None = None


def prepare_aws(
    profile: str | None = None, *, expected_account: str | None = None
) -> AwsIdentity:
    _require_aws_calls_allowed()
    if expected_account is not None and not valid_aws_account(expected_account):
        raise ProviderFailure(
            "not_configured", "AWS_COSTS_ACCOUNT_ID must be a 12-digit account ID."
        )
    with _aws_sdk() as (boto3, Config):
        session = boto3.Session(profile_name=profile)
        credentials = session.get_credentials()
        if credentials is None:
            raise ProviderFailure(
                "not_configured",
                "Configure AWS read-only billing credentials or AWS_COSTS_PROFILE.",
            )
        frozen = credentials.get_frozen_credentials()
        config = Config(
            connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 1}
        )
        captured = AwsCredentialsSnapshot(
            session, config, frozen.access_key, frozen.secret_key, frozen.token
        )
        with closing(captured.client("sts")) as identity:
            with billable_operation(
                "aws_sts",
                "get_caller_identity",
                source="costs",
                reason="cost_dashboard",
                billing="nonbillable",
                sdk_retries=0,
            ):
                response = identity.get_caller_identity()
                account = (
                    response.get("Account") if isinstance(response, dict) else None
                )
        if not valid_aws_account(account):
            raise ProviderFailure(
                "invalid_response", "AWS returned an invalid account identity."
            )
        if expected_account is not None and account != expected_account:
            raise ProviderFailure(
                "account_mismatch",
                f"Expected AWS account {expected_account}, but {profile or 'the default credential chain'} authenticates as {account}. Configure credentials for the application account or select an existing AWS_COSTS_PROFILE.",
            )
        return AwsIdentity(account, captured, getattr(session, "profile_name", profile))


def fetch_aws(
    now: datetime,
    profile: str | None = None,
    *,
    prepared: AwsIdentity | None = None,
) -> CostReport:
    _require_aws_calls_allowed()
    captured = prepared if prepared is not None else prepare_aws(profile)
    with _aws_sdk(), closing(captured.credentials.client("ce")) as client:
        return collect_aws(client, captured.account_id, now)
