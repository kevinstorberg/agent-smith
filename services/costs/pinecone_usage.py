from __future__ import annotations

from datetime import date, datetime, timedelta
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from services.costs.contracts import (
    CollectionResult,
    CostReport,
    ProviderFailure,
    require_utc,
    validate_pricing_source,
)
from services.costs.periods import month_window
from services.costs.pinecone_metrics import MetricSample
from services.costs.pinecone_pricing import (
    STANDARD_PRICE_DATE,
    STANDARD_PRICE_SOURCE,
    is_placeholder,
    optional_setting,
    standard_price_values,
    valid_rate_scope,
)


class UsageRate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    read_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    write_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)


class PriceBook(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    as_of: date
    source: str
    rates: dict[str, UsageRate]

    _source = field_validator("source")(validate_pricing_source)

    @field_validator("rates")
    @classmethod
    def region_rates(cls, value):
        if (
            not value
            or len(value) > 32
            or any(not valid_rate_scope(key) for key in value)
        ):
            raise ValueError(
                "PINECONE_COSTS_RATES_JSON must name explicit cloud/region rates"
            )
        return value

    @classmethod
    def from_env(cls, env, now):
        return resolve_price_book(env, now).book


@dataclass(frozen=True)
class ResolvedPricing:
    book: PriceBook
    note: str | None


def _rate_override(raw: str | None) -> dict | None:
    if raw is not None and (not isinstance(raw, str) or len(raw) > 32_000):
        raise ValueError("PINECONE_COSTS_RATES_JSON exceeds its supported text limit.")
    raw = optional_setting(raw)
    if raw is None:
        return None
    try:
        rates = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError(
            "PINECONE_COSTS_RATES_JSON must contain a cloud/region rate map."
        ) from None
    if not isinstance(rates, dict):
        raise ValueError(
            "PINECONE_COSTS_RATES_JSON must contain a cloud/region rate map."
        )
    if (
        0 < len(rates) <= 32
        and all(valid_rate_scope(key) for key in rates)
        and all(
            isinstance(values, dict)
            and set(values) == {"read_usd_per_million", "write_usd_per_million"}
            and all(is_placeholder(value) for value in values.values())
            for values in rates.values()
        )
    ):
        return None
    return rates


def resolve_price_book(env, now: datetime) -> ResolvedPricing:
    now = require_utc(now)
    rates = _rate_override(env.get("PINECONE_COSTS_RATES_JSON"))
    date_override = optional_setting(env.get("PINECONE_COSTS_PRICE_DATE"))
    source_override = optional_setting(env.get("PINECONE_COSTS_PRICE_SOURCE"))
    values = standard_price_values()
    if rates is not None:
        values["rates"] = rates
    if date_override is not None:
        values["as_of"] = date_override
    if source_override is not None:
        values["source"] = source_override
    try:
        book = PriceBook.model_validate(values)
    except ValidationError as error:
        field = error.errors(include_input=False)[0]["loc"][0]
        messages = {
            "rates": "PINECONE_COSTS_RATES_JSON must map cloud/region scopes to finite nonnegative read/write prices.",
            "as_of": "PINECONE_COSTS_PRICE_DATE must be a valid nonfuture date when supplied.",
            "source": "PINECONE_COSTS_PRICE_SOURCE must be an HTTP(S) URL without embedded credentials.",
        }
        raise ValueError(messages[field]) from None
    if book.as_of > now.date():
        raise ValueError(
            "PINECONE_COSTS_PRICE_DATE must be a valid nonfuture date when supplied."
        )
    custom = (
        rates is not None
        or book.as_of != STANDARD_PRICE_DATE
        or book.source != STANDARD_PRICE_SOURCE
    )
    note = (
        "Environment pricing overrides are user-supplied; the reference date is metadata, not independent verification of custom rates."
        if custom
        else None
    )
    return ResolvedPricing(book, note)


class StoredCounter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Literal["read_units", "write_units"]
    value: Decimal = Field(ge=0, allow_inf_nan=False)
    scope: str
    group: str


class ObservedInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: AwareDatetime
    end: AwareDatetime
    price_id: str | None
    usage: dict[str, tuple[Decimal | None, Decimal | None]] = Field(
        default_factory=dict
    )
    limitations: list[str] = Field(default_factory=list)


class UsageLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    month: str
    sampled_at: AwareDatetime
    coverage_start: AwareDatetime
    counters: dict[str, StoredCounter]
    intervals: list[ObservedInterval] = Field(default_factory=list, max_length=10000)
    prices: dict[str, PriceBook] = Field(default_factory=dict)


_LIMITATIONS = {
    "billing_boundary": "Intervals crossing a UTC billing day or month boundary are excluded; their timing is unknown.",
    "collection_gap": "A collection gap is excluded; missing usage was not backfilled.",
    "counter_reset": "Reset counters establish a new baseline; the unknown reset portion is excluded.",
    "series_churn": "New or disappearing metric series leave an unobserved portion of usage.",
    "unsupported_capacity": "Unsupported capacity modes, including dedicated read nodes, are excluded.",
    "unpriced": "Some observed usage has no applicable configured price and is excluded from the dollar estimate.",
}


def _price_identity(prices: PriceBook) -> str:
    return sha256(
        json.dumps(
            prices.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def amount(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _coverage(interval):
    return {
        scope: tuple(value is not None for value in values)
        for scope, values in interval.usage.items()
    }


def _append_interval(ledger, interval):
    previous = ledger.intervals[-1] if ledger.intervals else None
    if (
        previous
        and previous.end == interval.start
        and previous.start.date() == interval.end.date()
        and previous.price_id == interval.price_id
        and not previous.limitations
        and not interval.limitations
        and _coverage(previous) == _coverage(interval)
    ):
        previous.end = interval.end
        previous.usage = {
            scope: tuple(
                None if a is None else a + b
                for a, b in zip(previous.usage[scope], values)
            )
            for scope, values in interval.usage.items()
        }
    else:
        ledger.intervals.append(interval)


def build_usage(
    now: datetime,
    sample: MetricSample,
    previous_state: dict | None,
    prices: PriceBook | None,
    minimum: Decimal,
    *,
    pricing_note: str | None = None,
) -> CollectionResult:
    now = require_utc(now)
    if (
        not minimum.is_finite()
        or minimum < 0
        or (prices is not None and prices.as_of > now.date())
    ):
        raise ProviderFailure(
            "configuration_error",
            "Pinecone prices and monthly commitment must be valid and nonnegative.",
        )
    try:
        previous = (
            UsageLedger.model_validate(previous_state)
            if previous_state is not None
            else None
        )
    except ValidationError:
        raise ProviderFailure(
            "invalid_snapshot",
            "The Pinecone baseline snapshot is invalid; restore the private cache before collecting.",
        ) from None
    if previous and any(
        stamp != _price_identity(book) for stamp, book in previous.prices.items()
    ):
        raise ProviderFailure(
            "invalid_snapshot",
            "Pinecone pricing stamps do not match the persisted configuration.",
        )
    if previous and now <= previous.sampled_at:
        raise ProviderFailure(
            "clock_error", "Pinecone samples require a later UTC collection time."
        )
    counters = {
        identity: StoredCounter(
            metric=point.metric,
            value=point.value,
            scope=point.labels["cloud"] + "/" + point.labels["region"],
            group=point.group,
        )
        for identity, point in sample.counters.items()
    }
    month = now.strftime("%Y-%m")
    ledger = (
        previous.model_copy(deep=True)
        if previous and previous.month == month
        else UsageLedger(
            month=month, sampled_at=now, coverage_start=now, counters=counters
        )
    )
    price_id = None
    if prices is not None:
        price_id = _price_identity(prices)
        ledger.prices[price_id] = prices
    if previous:
        interval = ObservedInterval(
            start=previous.sampled_at, end=now, price_id=price_id
        )
        if previous.sampled_at.date() != now.date():
            interval.limitations.append("billing_boundary")
        elif now - previous.sampled_at > timedelta(minutes=15):
            interval.limitations.append("collection_gap")
        else:
            if counters.keys() != previous.counters.keys():
                interval.limitations.append("series_churn")
            for identity, point in counters.items():
                if point.group in sample.unsupported:
                    interval.limitations.append("unsupported_capacity")
                    continue
                before = previous.counters.get(identity)
                if before is None:
                    continue
                if (
                    before.metric != point.metric
                    or before.scope != point.scope
                    or before.group != point.group
                ):
                    raise ProviderFailure(
                        "invalid_snapshot",
                        "Pinecone counter identity does not match its persisted baseline.",
                    )
                if point.value < before.value:
                    interval.limitations.append("counter_reset")
                    continue
                values = list(interval.usage.get(point.scope, (None, None)))
                index = 0 if point.metric == "read_units" else 1
                values[index] = (
                    (values[index] or Decimal(0)) + point.value - before.value
                )
                interval.usage[point.scope] = tuple(values)
        interval.limitations = sorted(set(interval.limitations))
        _append_interval(ledger, interval)
    ledger.sampled_at = now
    ledger.counters = counters
    total = Decimal(0)
    daily = {}
    breakdown = {}
    units = [None, None]
    priced = False
    limitations = set()
    for interval in ledger.intervals:
        limitations.update(interval.limitations)
        stamped = ledger.prices.get(interval.price_id) if interval.price_id else None
        for scope, values in interval.usage.items():
            for index, value in enumerate(values):
                if value is not None:
                    units[index] = (units[index] or Decimal(0)) + value
            rate = stamped.rates.get(scope) if stamped else None
            if rate is None:
                limitations.add("unpriced")
                continue
            cost = (
                (values[0] or Decimal(0)) * rate.read_usd_per_million
                + (values[1] or Decimal(0)) * rate.write_usd_per_million
            ) / Decimal(1_000_000)
            total += cost
            priced = True
            day = interval.start.date().isoformat()
            daily[day] = daily.get(day, Decimal(0)) + cost
            breakdown[scope] = breakdown.get(scope, Decimal(0)) + cost
    notes = [
        "History before the monitoring baseline is unavailable.",
        "Storage is a current quantity only; storage cost is excluded.",
        "Backups, egress, inference, Assistant and dedicated read-node charges are excluded.",
        f"Standard monthly commitment: USD {amount(minimum)}. Shown separately from this observed usage estimate.",
        "Observed usage estimates cover collected intervals, not the complete month or final invoice.",
    ]
    if prices is None:
        notes.append(
            "Configure dated cloud/region prices to calculate dollar estimates; usage remains visible."
        )
    else:
        notes.append(
            f"Configured price date: {prices.as_of.isoformat()}; source: {prices.source}"
        )
        if (now.date() - prices.as_of).days > 30:
            notes.append(
                "Configured prices are older than 30 days; verify current applicable rates before relying on estimates."
            )
    if sample.unsupported:
        limitations.add("unsupported_capacity")
    if pricing_note is not None:
        notes.append(pricing_note)
    notes.extend(_LIMITATIONS[code] for code in sorted(limitations))
    active_scopes = {
        point.scope
        for point in counters.values()
        if point.group not in sample.unsupported
    }
    available = prices is not None and priced and active_scopes <= prices.rates.keys()
    missing_scopes = (
        active_scopes - prices.rates.keys() if prices is not None else set()
    )
    if missing_scopes:
        scope_description = (
            next(iter(missing_scopes))
            if len(missing_scopes) == 1
            else f"{len(missing_scopes)} observed cloud/region scopes"
        )
        notes.append(
            f"No applicable read/write prices are available for {scope_description}; quantities remain visible."
        )
    if not available:
        daily = {}
        breakdown = {}
    start, end = month_window(now)
    report = CostReport(
        provider="pinecone",
        period_start=start,
        period_end=end,
        currency="USD",
        total=amount(total) if available else None,
        pricing_source=prices.source if prices else None,
        pricing_as_of=prices.as_of if prices else None,
        estimated=True,
        scope="Configured Pinecone project: observed serverless usage only",
        fetched_at=now,
        coverage_start=ledger.coverage_start,
        cost_basis="Observed RU/WU at configured prices",
        daily=[
            {"label": key, "amount": amount(value)}
            for key, value in sorted(daily.items())
        ],
        breakdown=[
            {"label": key, "amount": amount(value)}
            for key, value in sorted(breakdown.items())
        ],
        usage=[
            {
                "label": label,
                "amount": amount(value) if value is not None else "Unavailable",
                "unit": unit,
            }
            for label, value, unit in [
                ("Observed read units", units[0], "RU"),
                ("Observed write units", units[1], "WU"),
                (
                    "Current stored data",
                    sum((point.value for point in sample.storage.values()), Decimal(0))
                    if sample.storage
                    else None,
                    "bytes",
                ),
            ]
        ],
        notes=notes,
    )
    if len(ledger.intervals) > 10000:
        raise ProviderFailure(
            "state_limit",
            "Pinecone interval history exceeded its configured safety limit.",
        )
    return CollectionResult(report, ledger.model_dump(mode="json"))
