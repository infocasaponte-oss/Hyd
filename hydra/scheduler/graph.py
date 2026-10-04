# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Execution graph: each query can become a DAG executed in parallel waves."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

NodeFn = Callable[[dict[str, Any]], Awaitable[Any]]


class CycleError(ValueError):
    pass


class ExecutionGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, NodeFn] = {}
        self.deps: dict[str, set[str]] = {}

    def add_node(self, name: str, fn: NodeFn) -> None:
        self.nodes[name] = fn
        self.deps.setdefault(name, set())

    def add_edge(self, before: str, after: str) -> None:
        if before not in self.nodes or after not in self.nodes:
            raise KeyError(f"unknown node in edge {before} -> {after}")
        self.deps[after].add(before)

    def waves(self) -> list[list[str]]:
        remaining = {n: set(d) for n, d in self.deps.items()}
        waves: list[list[str]] = []
        while remaining:
            ready = sorted(n for n, d in remaining.items() if not d)
            if not ready:
                raise CycleError(f"cycle among {sorted(remaining)}")
            waves.append(ready)
            for n in ready:
                del remaining[n]
            for d in remaining.values():
                d.difference_update(ready)
        return waves

    async def execute_parallel(self, max_concurrency: int = 8) -> dict[str, Any]:
        """Run the DAG; each node receives the outputs of its dependencies."""
        results: dict[str, Any] = {}
        sem = asyncio.Semaphore(max_concurrency)

        async def run(name: str) -> None:
            async with sem:
                inputs = {d: results[d] for d in self.deps[name]}
                results[name] = await self.nodes[name](inputs)

        for wave in self.waves():
            async with asyncio.TaskGroup() as tg:
                for name in wave:
                    tg.create_task(run(name))
        return results
