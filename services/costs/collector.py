from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress

from services.costs.service import _enabled, collect_pinecone_costs
from services.observability import work_decision


@asynccontextmanager
async def pinecone_collector(*, collect=None):
    try:
        enabled = _enabled("PINECONE_COSTS_ENABLED")
    except ValueError:
        enabled = False
    if not enabled:
        yield
        return

    from scripts.shared.owned_thread import run_owned_thread

    operation = collect if collect is not None else collect_pinecone_costs

    async def run():
        while True:
            work_decision(
                "cost_collection_triggered",
                source="costs",
                reason="five_minute_metrics",
            )
            try:
                await run_owned_thread(
                    operation, failure_context="In-flight Pinecone collection failed"
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                work_decision(
                    "cost_collection_failed",
                    source="costs",
                    outcome="failed",
                    error_type=type(error).__name__,
                )
            await asyncio.sleep(300)

    task = asyncio.create_task(run(), name="pinecone-costs-collector")
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
