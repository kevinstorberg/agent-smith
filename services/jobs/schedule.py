"""Interval parsing and validation for background job schedules.

Background Processes V1 supports interval scheduling only: a ``schedule_config``
is a non-empty dict whose keys are a subset of seconds/minutes/hours/days, each
mapping to a positive number. A job with no valid interval must never be
scheduled, so invalid configs are rejected loudly at the boundary.
"""
from __future__ import annotations

from datetime import timedelta

INTERVAL_KEYS = ("seconds", "minutes", "hours", "days")


def parse_interval(schedule_config: dict) -> timedelta:
    """Convert an interval ``schedule_config`` into a ``timedelta``.

    Raises ``ValueError`` with a descriptive message if the config is empty,
    has unsupported keys, or contains a non-positive / non-numeric value.
    """
    if not isinstance(schedule_config, dict) or not schedule_config:
        raise ValueError(
            "schedule_config must be a non-empty interval dict, e.g. {'minutes': 5}"
        )

    unknown = set(schedule_config) - set(INTERVAL_KEYS)
    if unknown:
        raise ValueError(
            f"schedule_config has unsupported keys {sorted(unknown)}; "
            f"allowed keys are {list(INTERVAL_KEYS)}"
        )

    kwargs: dict[str, float] = {}
    for key, value in schedule_config.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(
                f"schedule_config['{key}'] must be a positive number, got {value!r}"
            )
        kwargs[key] = value

    interval = timedelta(**kwargs)
    if interval.total_seconds() <= 0:
        raise ValueError("schedule_config must describe a positive interval")
    return interval
