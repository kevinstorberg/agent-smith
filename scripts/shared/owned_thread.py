from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


async def run_owned_thread(operation: Callable[[], T], *, failure_context: str) -> T:
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as cancelled:
        # Cancellation cannot release resources still used by the worker thread.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if task.done() and not task.cancelled():
            try:
                task.result()
            except Exception as error:
                cancelled.add_note(f"{failure_context}: {type(error).__name__}")
        raise cancelled
