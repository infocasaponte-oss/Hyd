# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Cognitive budget: every task gets a finite amount of thinking."""

from __future__ import annotations

import time

from pydantic import BaseModel

from hydra.core.contracts import ExecutionMode, HydraRequest
from hydra.core.inference_budget import InferenceBudget


class CognitiveBudget(BaseModel):
    max_tokens: int
    max_model_calls: int
    max_tool_calls: int
    max_seconds: float
    max_cost: float
    max_parallel_workers: int
    max_steps: int = 8
    max_escalations: int = 2


PRESETS: dict[ExecutionMode, CognitiveBudget] = {
    ExecutionMode.FAST: CognitiveBudget(
        max_tokens=8_000, max_model_calls=1, max_tool_calls=2, max_seconds=30,
        max_cost=0.01, max_parallel_workers=1, max_steps=2, max_escalations=0,
    ),
    ExecutionMode.BALANCED: CognitiveBudget(
        max_tokens=32_000, max_model_calls=4, max_tool_calls=6, max_seconds=45,
        max_cost=0.10, max_parallel_workers=2, max_steps=6, max_escalations=1,
    ),
    ExecutionMode.DEEP: CognitiveBudget(
        max_tokens=128_000, max_model_calls=12, max_tool_calls=20, max_seconds=120,
        max_cost=1.00, max_parallel_workers=5, max_steps=12, max_escalations=2,
    ),
    ExecutionMode.MAX: CognitiveBudget(
        max_tokens=512_000, max_model_calls=30, max_tool_calls=50, max_seconds=600,
        max_cost=5.00, max_parallel_workers=8, max_steps=24, max_escalations=4,
    ),
    ExecutionMode.PRIVATE: CognitiveBudget(
        max_tokens=64_000, max_model_calls=8, max_tool_calls=12, max_seconds=120,
        max_cost=0.0, max_parallel_workers=3, max_steps=8, max_escalations=2,
    ),
}


def budget_for(request: HydraRequest, time_scale: float = 1.0) -> CognitiveBudget:
    """``time_scale`` stretches wall-clock budgets (e.g. local hardware with cold model loads)."""
    budget = PRESETS[request.mode].model_copy()
    # A visual task needs perception followed by the answer. FAST's one-call
    # text preset otherwise consumes its entire allowance before answering.
    if request.images and request.mode == ExecutionMode.FAST:
        budget.max_model_calls = 2
    budget.max_seconds *= time_scale
    if request.max_cost is not None:
        budget.max_cost = request.max_cost
    if request.max_latency_ms is not None:
        budget.max_seconds = min(budget.max_seconds, request.max_latency_ms / 1000)
    return budget


class BudgetExceeded(RuntimeError):
    pass


class BudgetTracker:
    def __init__(self, budget: CognitiveBudget) -> None:
        self.budget = budget
        self.started = time.monotonic()
        self.tokens = 0
        # Model calls live in the same counter the native executors use, so a task's
        # cognitive, physical and logical inference share one budget.
        self.calls = InferenceBudget(budget.max_model_calls)
        self.tool_calls = 0
        self.cost = 0.0
        self.steps = 0
        self.escalations = 0

    @property
    def model_calls(self) -> int:
        return self.calls.used

    def _sync_limit(self) -> InferenceBudget:
        self.calls.limit = self.budget.max_model_calls
        return self.calls

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.budget.max_seconds - self.elapsed_s)

    def can_call_model(self, n: int = 1) -> bool:
        calls = self._sync_limit()
        return calls.used + n <= calls.limit and not self.exhausted

    def reserve_model_call(self) -> None:
        """Reserve before calling, so concurrent (hedged) calls cannot overrun the budget.

        Pair with ``release_model_call`` when the attempt fails: only successful calls count,
        so a FAST task (one call) can still retry after a failure.
        """
        if self.exhausted or not self._sync_limit().reserve():
            raise BudgetExceeded("model call budget exhausted")

    def release_model_call(self) -> None:
        """Return the unit of a failed or cancelled attempt."""
        self.calls.release(1)

    def can_call_tool(self) -> bool:
        return self.tool_calls < self.budget.max_tool_calls and not self.exhausted

    def can_escalate(self) -> bool:
        return self.escalations < self.budget.max_escalations and self.can_call_model()

    def charge_model(self, tokens: int, cost: float, *, reserved: bool = False) -> None:
        if not reserved:
            self.calls.used += 1
        self.tokens += tokens
        self.cost += cost

    def charge_tool(self) -> None:
        if not self.can_call_tool():
            raise BudgetExceeded("tool call budget exhausted")
        self.tool_calls += 1

    @property
    def exhausted(self) -> bool:
        b = self.budget
        return (
            self.tokens >= b.max_tokens
            or self.elapsed_s >= b.max_seconds
            or (b.max_cost > 0 and self.cost >= b.max_cost)
        )

    @property
    def max_steps_reached(self) -> bool:
        return self.steps >= self.budget.max_steps

    def snapshot(self) -> dict:
        return {
            "tokens": self.tokens,
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "cost": round(self.cost, 6),
            "steps": self.steps,
            "escalations": self.escalations,
            "elapsed_s": round(self.elapsed_s, 3),
        }
