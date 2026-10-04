# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Small async public API over the existing HYDRA kernel."""
from __future__ import annotations

from typing import Self

from hydra.core.bootstrap import HydraRuntime, build_runtime
from hydra.core.config import Settings
from hydra.core.contracts import ExecutionMode, HydraRequest, HydraResponse, Message


class HydraEngine:
    """Reuse one runtime across queries; use an async context manager to own its lifetime."""

    def __init__(self, runtime: HydraRuntime, *, owns_runtime: bool = False) -> None:
        self.runtime = runtime
        self._owns_runtime = owns_runtime
        self._closed = False

    @classmethod
    async def create(cls, settings: Settings | None = None) -> Self:
        return cls(await build_runtime(settings), owns_runtime=True)

    async def __aenter__(self) -> Self:
        if self._closed:
            raise RuntimeError("engine is closed")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._owns_runtime:
                await self.runtime.close()

    async def query(
        self, prompt: str, *, context: str | None = None,
        images: list[str] | None = None, mode: ExecutionMode = ExecutionMode.BALANCED,
        local_only: bool = True, use_cache: bool = True,
        max_cost: float | None = None, max_latency_ms: int | None = None,
    ) -> HydraResponse:
        """Context is actual text, not a filename. Images follow Message's URI contract.

        Local inference is the default. Advanced permissions and history use execute().
        No provider credentials, retries, memory or decision policy are duplicated here.
        """
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be nonempty text")
        if context is not None and not isinstance(context, str):
            raise TypeError("context must be text")
        messages = []
        if context:
            messages.append(Message(role="user", content="Reference material supplied by the user:\n" + context))
        messages.append(Message(role="user", content=prompt, images=list(images or [])))
        return await self.execute(HydraRequest(
            messages=messages, mode=mode, local_only=local_only, use_cache=use_cache,
            max_cost=max_cost, max_latency_ms=max_latency_ms))

    async def execute(self, request: HydraRequest) -> HydraResponse:
        """Full typed contract, including history and explicit action approvals."""
        if self._closed:
            raise RuntimeError("engine is closed")
        return await self.runtime.kernel.run(request)
