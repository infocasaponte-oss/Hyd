# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Parallel ensembles, hedged requests and speculative execution with cancellation."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")
Call = Callable[[], Awaitable[T]]


async def run_parallel(calls: list[Call]) -> list[Any]:
    """Run every call concurrently. A failure does not cancel the others:
    the exception is returned in its slot so the caller can decide."""

    async def guard(call: Call):
        try:
            return await call()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return exc

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(guard(call)) for call in calls]
    return [t.result() for t in tasks]


async def _cancel(tasks) -> None:
    for t in tasks:
        t.cancel()
    for t in tasks:
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await t


async def hedged(primary: Call, backup: Call | None, hedge_after_s: float) -> tuple[Any, str]:
    """Hedged execution: if the primary is slow, launch a backup and keep the
    first acceptable response; cancel the other. Returns (result, 'primary'|'backup')."""
    p = asyncio.create_task(primary())
    if backup is None:
        return await p, "primary"
    done, _ = await asyncio.wait({p}, timeout=hedge_after_s)
    if done:
        # A fast failure is not a latency problem: surface it so the caller can
        # classify it, trip the circuit breaker and choose a typed retry.
        return p.result(), "primary"

    b = asyncio.create_task(backup())
    pending = {p, b}
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if t.exception() is None:
                await _cancel(pending)
                return t.result(), ("primary" if t is p else "backup")
    # Both failed. The primary's error is the real diagnostic: the backup may only have been
    # refused before running (e.g. no budget left), which must not hide a failing primary.
    raise p.exception()


async def speculative(
    calls: list[Call],
    accept: Callable[[Any], bool],
) -> tuple[Any | None, list[Any]]:
    """Speculative reasoning: launch every path, return as soon as one result is
    acceptable and cancel the rest. Returns (winner or None, all finished results)."""
    tasks = [asyncio.create_task(c()) for c in calls]
    finished: list[Any] = []
    pending = set(tasks)
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                result = t.exception() or t.result()
                finished.append(result)
                if not isinstance(result, BaseException) and accept(result):
                    await _cancel(pending)
                    return result, finished
        return None, finished
    finally:
        await _cancel([t for t in tasks if not t.done()])
