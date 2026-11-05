from datetime import date
from decimal import Decimal
import re


STANDARD_PRICE_DATE = date(2026, 11, 5)
STANDARD_PRICE_SOURCE = "https://www.pinecone.io/pricing/"
STANDARD_MONTHLY_MINIMUM_USD = Decimal("50")

# The dated Standard cloud/region table is authoritative; no prices are inferred.
_STANDARD_RATES = (
    ("aws/us-east-1", "16", "4"),
    ("aws/us-west-2", "16", "4"),
    ("aws/eu-west-1", "18", "4.50"),
    ("aws/eu-central-1", "19", "5"),
    ("aws/ap-southeast-1", "19", "5"),
    ("gcp/us-central1", "16", "4"),
    ("gcp/europe-west4", "18", "4.50"),
    ("azure/eastus2", "16", "4"),
)
_PLACEHOLDERS = frozenset(
    {
        "COPY_VERIFIED_RATE",
        "YYYY-MM-DD",
        "REPLACE_ME",
        "YOUR_PROJECT_ID",
        "YOUR_PINECONE_PROJECT_ID",
        "your-pinecone-api-key",
    }
)


def is_placeholder(value: object) -> bool:
    return isinstance(value, str) and (
        value.strip() in _PLACEHOLDERS
        or re.fullmatch(r"REPLACE_WITH_[A-Z0-9_]+", value.strip()) is not None
    )


def optional_setting(value: str | None) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError("Pinecone settings must be text.")
    return (
        None if value is None or not value.strip() or is_placeholder(value) else value
    )


def valid_rate_scope(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"(aws|gcp|azure)/[a-z0-9-]{1,64}", value) is not None
    )


def standard_price_values() -> dict:
    return {
        "as_of": STANDARD_PRICE_DATE,
        "source": STANDARD_PRICE_SOURCE,
        "rates": {
            scope: {"read_usd_per_million": read, "write_usd_per_million": write}
            for scope, read, write in _STANDARD_RATES
        },
    }
