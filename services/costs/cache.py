from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import json
import logging
from pathlib import Path

from pydantic import ValidationError

from scripts.shared.atomic_json import atomic_write_json, exclusive_file_lock
from services.costs.contracts import (
    CollectionResult,
    CostReport,
    ProviderFailure,
    Snapshot,
    require_utc,
)


class SnapshotCache:
    def __init__(
        self,
        directory: Path,
        provider: str,
        scope: str,
        *,
        success_interval: timedelta = timedelta(days=1),
        failure_interval: timedelta = timedelta(minutes=30),
        daily_attempt_limit: int = 3,
    ) -> None:
        if provider not in {"aws", "pinecone"} or not scope:
            raise ValueError("Cost cache requires a known provider and scope")
        if (
            min(
                success_interval.total_seconds(),
                failure_interval.total_seconds(),
                daily_attempt_limit,
            )
            <= 0
        ):
            raise ValueError("Cost refresh limits must be positive")
        self.provider = provider
        self.key = sha256(f"{provider}:{scope}".encode()).hexdigest()
        self.path = Path(directory) / f"{self.key}.json"
        self.lock_path = self.path.with_suffix(".lock")
        self.success_interval = success_interval
        self.failure_interval = failure_interval
        self.daily_attempt_limit = daily_attempt_limit

    def _load(self) -> Snapshot | None:
        if self.path.is_symlink():
            raise ValueError("Refusing a symbolic cost snapshot")
        if not self.path.exists():
            return None
        if self.path.stat().st_size > 10_000_000:
            raise ValueError("Cost snapshot exceeds its size limit")
        try:
            snapshot = Snapshot.model_validate_json(self.path.read_bytes())
            if snapshot.cache_key != self.key:
                raise ValueError("Cost snapshot scope does not match")
            if (
                snapshot.report is not None
                and snapshot.report.provider != self.provider
            ):
                raise ValueError("Cost snapshot provider does not match")
            return snapshot
        except (ValidationError, json.JSONDecodeError) as error:
            raise ValueError(
                "Invalid cost snapshot; restore or remove the cached file"
            ) from error

    @staticmethod
    def _view(snapshot: Snapshot | None, *, pending: bool = False) -> dict:
        return {
            "state": "pending"
            if pending
            else "stale"
            if snapshot and snapshot.error and snapshot.report
            else "failed"
            if snapshot and snapshot.error
            else "ready"
            if snapshot and snapshot.report
            else "pending",
            "report": snapshot.report.model_dump(mode="json")
            if snapshot and snapshot.report
            else None,
            "error": snapshot.error if snapshot and not pending else None,
            "next_refresh_at": snapshot.next_attempt_at.isoformat()
            if snapshot
            else None,
        }

    def read(self) -> dict:
        return self._view(self._load())

    def read_or_refresh(self, now: datetime, fetch: Callable[[], CostReport]) -> dict:
        return self._read_or_collect(
            now, lambda _report, state: CollectionResult(fetch(), state)
        )

    def read_or_collect(
        self,
        now: datetime,
        collector: Callable[[CostReport | None, dict | None], CollectionResult],
    ) -> dict:
        return self._read_or_collect(now, collector)

    def _read_or_collect(
        self,
        now: datetime,
        collector: Callable[[CostReport | None, dict | None], CollectionResult],
    ) -> dict:
        now = require_utc(now)
        existing = self._load()
        if existing and now < existing.next_attempt_at:
            return self._view(existing)
        try:
            with exclusive_file_lock(self.lock_path, "Cost collection"):
                existing = self._load()
                if existing and now < existing.next_attempt_at:
                    return self._view(existing)
                attempts = (
                    existing.attempts
                    if existing and existing.attempt_day == now.date()
                    else 0
                )
                if attempts >= self.daily_attempt_limit:
                    return self._view(existing)
                pending = Snapshot(
                    cache_key=self.key,
                    next_attempt_at=now + self.failure_interval,
                    attempt_day=now.date(),
                    attempts=attempts + 1,
                    report=existing.report if existing else None,
                    state=deepcopy(existing.state) if existing else None,
                    error={
                        "code": "interrupted_refresh",
                        "message": "The last refresh did not finish. Collection will retry after the displayed time.",
                    },
                )
                atomic_write_json(self.path, pending.model_dump(mode="json"))
                try:
                    fresh = collector(
                        deepcopy(existing.report) if existing else None,
                        deepcopy(existing.state) if existing else None,
                    )
                    if (
                        not isinstance(fresh, CollectionResult)
                        or not isinstance(fresh.report, CostReport)
                        or fresh.report.provider != self.provider
                    ):
                        raise ProviderFailure(
                            "invalid_response",
                            "Provider returned an invalid cost report.",
                        )
                    if fresh.state is not None:
                        if not isinstance(fresh.state, dict):
                            raise ValueError("Collection state must be a JSON object")
                        encoded = json.dumps(
                            fresh.state, ensure_ascii=False, indent=2, allow_nan=False
                        )
                        if len(encoded.encode("utf-8")) > 8_000_000:
                            raise ValueError("Collection state exceeds its size limit")
                except Exception as error:
                    safe = (
                        error
                        if isinstance(error, ProviderFailure)
                        else ProviderFailure(
                            "unavailable",
                            "Cost collection failed. Check server configuration and provider access.",
                        )
                    )
                    pending.error = {"code": safe.code, "message": safe.message}
                    logging.getLogger("agent_smith.costs").warning(
                        "%s COST REFRESH FAILED: %s", self.provider.upper(), safe.code
                    )
                else:
                    pending.report = deepcopy(fresh.report)
                    pending.state = deepcopy(fresh.state)
                    pending.error = None
                    pending.next_attempt_at = now + self.success_interval
                atomic_write_json(self.path, pending.model_dump(mode="json"))
                return self._view(pending)
        except RuntimeError as error:
            if (
                str(error)
                != "Cost collection is already running; retry after it finishes"
            ):
                raise
            return self._view(self._load(), pending=True)
