from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from concurrent.futures import CancelledError as FutureCancelledError, Executor, Future
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from datetime import datetime, timezone
from functools import partial
import json
import logging
import math
import re
from threading import Lock
import time
from types import MappingProxyType
from typing import Any, Callable, TypeVar
from uuid import UUID, uuid4


logger = logging.getLogger("agent_smith.billable")
logger.setLevel(logging.INFO)
_work_logger = logging.getLogger("agent_smith.work")
_work_logger.setLevel(logging.INFO)
_handler_lock = Lock()
_trigger: ContextVar[Mapping[str, Any] | None] = ContextVar(
    "billable_trigger", default=None
)
_CONTEXT_FIELDS = frozenset(
    {
        "trigger",
        "origin",
        "request_id",
        "client",
        "tool",
        "agent_tool",
        "graph",
        "graph_run_id",
        "job_id",
        "execution_id",
        "meeting_id",
        "profile_id",
        "source",
        "source_kind",
        "source_hash",
        "source_revision",
        "stage",
        "stage_status",
        "reason",
        "attempt",
        "manual_request_id",
        "requested_at",
        "checkpoint",
        "model_role",
        "model",
        "sdk_retries",
        "index",
        "namespace",
        "parent_event_id",
        "model_run_id",
        "parent_model_run_id",
        "count",
        "streaming",
        "billing",
        "input_messages",
        "input_characters",
    }
)
_END_FIELDS = frozenset(
    {
        "http_status",
        "exit_code",
        "tokens_input",
        "tokens_output",
        "total_tokens",
        "read_units",
        "write_units",
        "finish_reason",
        "completion",
    }
)
_OUTCOMES = frozenset({"success", "failed", "cancelled", "timeout", "unknown"})
_TIMEOUT_TYPES = frozenset(
    {
        ("httpx", "TimeoutException"),
        ("openai", "APITimeoutError"),
        ("anthropic", "APITimeoutError"),
        ("urllib3.exceptions", "TimeoutError"),
        ("botocore.exceptions", "ConnectTimeoutError"),
        ("botocore.exceptions", "ReadTimeoutError"),
        ("google.api_core.exceptions", "DeadlineExceeded"),
    }
)
_T = TypeVar("_T")


def _safe_fields(fields: Mapping[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    unexpected = fields.keys() - allowed
    if unexpected:
        raise ValueError(
            "Unsupported billable log fields: " + ", ".join(sorted(unexpected))
        )
    result = {}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, UUID):
            value = str(value)
        elif isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"Billable log field {key!r} must include a timezone")
            value = value.astimezone(timezone.utc).isoformat()
        if isinstance(value, str):
            value = value[:512]
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"Billable log field {key!r} must be finite")
        elif not isinstance(value, (int, bool)):
            raise ValueError(f"Billable log field {key!r} must be a scalar")
        result[key] = value
    return result


def current_trigger() -> dict[str, Any]:
    return dict(_trigger.get() or {})


@contextmanager
def trigger_context(**fields: Any) -> Iterator[None]:
    values = {**current_trigger(), **_safe_fields(fields, _CONTEXT_FIELDS)}
    token = _trigger.set(MappingProxyType(values))
    try:
        yield
    finally:
        _trigger.reset(token)


def _write_log(
    record: dict[str, Any], prefix: str, target_logger: logging.Logger, extra_name: str
) -> None:
    # CLI providers also need visible records when no application handler was installed.
    with _handler_lock:
        if not target_logger.hasHandlers():
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            target_logger.addHandler(handler)
            target_logger.propagate = False
    target_logger.info(
        "%s %s",
        prefix,
        json.dumps(record, ensure_ascii=False, sort_keys=True),
        extra={extra_name: record},
    )


def _emit(record: dict[str, Any]) -> None:
    _write_log(record, f"BILLABLE {record['phase']}", logger, "billable_event")


def work_decision(decision: str, **fields: Any) -> None:
    if not isinstance(decision, str) or not re.fullmatch(
        r"[a-z][a-z0-9_]{0,63}", decision
    ):
        raise ValueError("Work decision must be a short lowercase identifier")
    metadata = _safe_fields(
        fields, _CONTEXT_FIELDS | {"outcome", "error_type", "duration_ms"}
    )
    _write_log(
        {
            "trigger": "unknown",
            **current_trigger(),
            **metadata,
            "decision": decision,
            "utc_timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "WORK DECISION",
        _work_logger,
        "work_decision",
    )


class BillableEvent:
    def __init__(self, provider: str, operation: str, fields: dict[str, Any]) -> None:
        self.event_id = str(uuid4())
        self._started = time.monotonic()
        self._lock = Lock()
        self._finished = False
        self._fields = MappingProxyType(
            {
                "trigger": "unknown",
                "billing": "potential",
                **fields,
                "event_id": self.event_id,
                "provider": provider,
                "operation": operation,
            }
        )

    @classmethod
    def start(cls, provider: str, operation: str, **fields: Any) -> BillableEvent:
        if (
            not isinstance(provider, str)
            or not provider.strip()
            or not isinstance(operation, str)
            or not operation.strip()
        ):
            raise ValueError("Billable provider and operation must be nonblank strings")
        metadata = {**current_trigger(), **_safe_fields(fields, _CONTEXT_FIELDS)}
        event = cls(provider[:128], operation[:128], metadata)
        _emit(
            {
                **event._fields,
                "phase": "START",
                "utc_timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        return event

    def finish(
        self,
        outcome: str = "success",
        *,
        error: BaseException | None = None,
        **fields: Any,
    ) -> bool:
        if outcome not in _OUTCOMES:
            raise ValueError("Unsupported billable outcome")
        terminal = _safe_fields(fields, _END_FIELDS)
        if error is not None:
            terminal["error_type"] = type(error).__name__
            status = getattr(error, "status_code", None) or getattr(
                error, "status", None
            )
            if type(status) is int and 100 <= status <= 599:
                terminal.setdefault("http_status", status)
        with self._lock:
            if self._finished:
                return False
            _emit(
                {
                    **self._fields,
                    **terminal,
                    "phase": "END",
                    "outcome": outcome,
                    "duration_ms": round(
                        max(0, time.monotonic() - self._started) * 1000, 3
                    ),
                    "utc_timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._finished = True
        return True


def error_outcome(error: BaseException) -> str:
    if isinstance(
        error,
        (
            asyncio.CancelledError,
            FutureCancelledError,
            GeneratorExit,
            KeyboardInterrupt,
        ),
    ):
        return "cancelled"
    if isinstance(error, TimeoutError) or any(
        (kind.__module__, kind.__name__) in _TIMEOUT_TYPES
        for kind in type(error).__mro__
    ):
        return "timeout"
    return "failed"


@contextmanager
def billable_operation(
    provider: str, operation: str, **fields: Any
) -> Iterator[BillableEvent]:
    event = BillableEvent.start(provider, operation, **fields)
    with trigger_context(parent_event_id=event.event_id):
        try:
            yield event
        except BaseException as error:
            event.finish(error_outcome(error), error=error)
            raise
        else:
            event.finish()


def submit_with_context(
    executor: Executor, function: Callable[..., _T], *args: Any, **kwargs: Any
) -> Future[_T]:
    context = copy_context()
    return executor.submit(context.run, partial(function, *args, **kwargs))
