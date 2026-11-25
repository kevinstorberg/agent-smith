from __future__ import annotations

import math
import os
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass, field

from pinecone import Pinecone
from pinecone.config.openapi_configuration import Configuration
from pinecone.db_data.index import Index

from services.memory.backends import memory_ids
from services.memory.backends import pinecone_backend as backend
from services.memory.catalog import Source


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class MaintenanceBudget:
    max_records: int
    max_requests: int
    deadline_seconds: float
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    records: int = field(init=False, default=0)
    requests: int = field(init=False, default=0)
    deadline: float = field(init=False)

    def __post_init__(self) -> None:
        if type(self.max_records) is not int or self.max_records <= 0:
            raise ValueError("Memory maintenance record budget must be positive")
        if type(self.max_requests) is not int or self.max_requests <= 0:
            raise ValueError("Memory maintenance request budget must be positive")
        if (
            type(self.deadline_seconds) not in (int, float)
            or not math.isfinite(self.deadline_seconds)
            or self.deadline_seconds <= 0
        ):
            raise ValueError("Memory maintenance deadline must be finite and positive")
        self.deadline = self.clock() + self.deadline_seconds

    def check(self) -> float:
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError("Memory maintenance exceeded its deadline")
        return remaining

    def request(self) -> float:
        remaining = self.check()
        if self.requests >= self.max_requests:
            raise BudgetExceeded("Memory maintenance exceeded its request budget")
        self.requests += 1
        return min(backend.REQUEST_SECONDS, remaining)

    def reserve_records(self, count: int) -> None:
        self.check()
        if type(count) is not int or count < 0:
            raise ValueError("Memory maintenance record count must be nonnegative")
        if self.records + count > self.max_records:
            raise BudgetExceeded("Memory maintenance exceeded its record budget")
        self.records += count


@contextmanager
def open_index(source: Source, budget: MaintenanceBudget):
    if not isinstance(source, Source) or source.namespace:
        raise ValueError("Memory maintenance requires the configured default namespace")
    api_key = os.environ.get("PINECONE_API_KEY")
    if not api_key:
        raise ValueError("PINECONE_API_KEY is required for memory maintenance")
    control = Pinecone(api_key=api_key, host="https://api.pinecone.io", pool_threads=1)
    control._openapi_config.retries = 0
    api = control.db.index._index_api
    with closing(api.api_client):
        description = backend._ObservedPinecone(api).describe_index(
            index_name=source.index_name, _request_timeout=budget.request()
        )
        budget.check()
        host = backend._response_field(description, "host")
        if not isinstance(host, str) or not host.strip():
            raise RuntimeError("Pinecone index discovery did not return a host")
        configuration = Configuration()
        configuration.retries = 0
        with Index(
            api_key=api_key,
            host=host,
            openapi_config=configuration,
            pool_threads=1,
        ) as raw_index:
            yield backend._ObservedPinecone(raw_index, index=source.index_name)


def fetch_rows(
    index, ids: list[str], budget: MaintenanceBudget, *, strict: bool = True
) -> list[dict]:
    if len(ids) > backend.LIST_PAGE_SIZE:
        raise ValueError("Memory maintenance fetch exceeds its bounded batch size")
    if strict:
        normalized = memory_ids(ids)
        if normalized != ids:
            raise ValueError("Memory maintenance IDs must be unique canonical UUIDs")
    if not ids:
        return []
    budget.request()
    rows = backend._fetch_rows(ids, index, budget.deadline)
    if strict and [row["id"] for row in rows] != ids:
        raise RuntimeError("Memory maintenance fetched an incomplete page")
    return rows


def iter_rows(
    index, budget: MaintenanceBudget, *, strict: bool = True
) -> Iterator[list[dict]]:
    seen_ids: set[str] = set()
    seen_tokens: set[str] = set()
    token: str | None = None
    pages = rows_seen = 0
    stage = "list"
    try:
        while True:
            stage = "list"
            remaining_records = budget.max_records - budget.records
            if remaining_records <= 0:
                raise BudgetExceeded("Memory maintenance exceeded its record budget")
            page_size = min(backend.LIST_PAGE_SIZE, remaining_records)
            page = index.list_paginated(
                limit=page_size,
                pagination_token=token,
                _request_timeout=budget.request(),
            )
            pages += 1
            budget.check()
            stage = "decode"
            prefix = f"Pinecone memory enumeration page {pages}"
            vectors = backend._response_field(page, "vectors")
            if not isinstance(vectors, list) or len(vectors) > page_size:
                raise RuntimeError(
                    f"{prefix} must contain at most {page_size} vector IDs"
                )
            ids = []
            for vector in vectors:
                id = backend._response_field(vector, "id")
                if not isinstance(id, str) or not id.strip():
                    raise RuntimeError(f"{prefix} contains an invalid vector ID")
                if id in seen_ids:
                    if strict:
                        raise RuntimeError(f"{prefix} repeated a vector ID")
                    continue
                seen_ids.add(id)
                ids.append(id)
            if strict and memory_ids(ids) != ids:
                raise RuntimeError(f"{prefix} contains noncanonical vector IDs")
            budget.reserve_records(len(ids))

            pagination = backend._response_field(page, "pagination")
            if (
                pagination is not None
                and not isinstance(pagination, Mapping)
                and not hasattr(pagination, "get")
            ):
                raise RuntimeError(f"{prefix} contains invalid pagination metadata")
            next_token = backend._response_field(pagination, "next")
            if next_token is not None:
                if not isinstance(next_token, str) or not next_token.strip():
                    raise RuntimeError(
                        f"{prefix} contains an invalid continuation token"
                    )
                if next_token in seen_tokens:
                    raise RuntimeError(f"{prefix} repeated a continuation token")
                seen_tokens.add(next_token)

            stage = "fetch"
            rows = fetch_rows(index, ids, budget, strict=strict)
            rows_seen += len(rows)
            budget.check()
            yield rows
            if next_token is None:
                return
            token = next_token
    except TimeoutError as error:
        raise TimeoutError(
            f"Pinecone memory enumeration timed out during {stage} after {pages} pages "
            f"and {rows_seen} rows ({budget.deadline_seconds:g}-second overall deadline)"
        ) from error
    except Exception as error:
        error.add_note(
            f"Pinecone memory enumeration failed during {stage} after {pages} pages and {rows_seen} rows"
        )
        raise


def legacy_rows(index) -> list[dict]:
    budget = MaintenanceBudget(
        max_records=sys.maxsize,
        max_requests=sys.maxsize,
        deadline_seconds=backend.ENUMERATION_SECONDS,
        clock=backend.time.monotonic,
    )
    return [row for batch in iter_rows(index, budget, strict=False) for row in batch]
