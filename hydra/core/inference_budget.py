# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


class ModelCallBudgetExceeded(RuntimeError):
    pass


@dataclass
class InferenceBudget:
    limit: int
    used: int = 0

    def reserve(self, count: int = 1) -> bool:
        """All-or-nothing: reserve ``count`` units only if all of them remain."""
        if count < 0 or self.used + count > self.limit:
            return False
        self.used += count
        return True

    def release(self, count: int) -> None:
        """Return units reserved for calls that were never attempted."""
        self.used = max(0, self.used - max(0, count))


_current: ContextVar[InferenceBudget | None] = ContextVar("hydra_inference_budget", default=None)


@contextmanager
def inference_budget(limit: int):
    with use_inference_budget(InferenceBudget(limit)) as budget:
        yield budget


@contextmanager
def use_inference_budget(budget: InferenceBudget):
    """Expose an existing counter (e.g. the cognitive kernel's) to every executor below."""
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)


def reserve_model_calls(count: int) -> int:
    """Reserve every call of a plan up front against the remaining shared budget.

    Returns the units reserved (0 outside a budget context). Raises before any inference
    when the plan cannot complete, instead of failing after spending earlier steps.
    """
    budget = _current.get()
    if budget is None or count <= 0:
        return 0
    if not budget.reserve(count):
        raise ModelCallBudgetExceeded("Execution plan exceeds remaining model-call budget")
    return count


def release_model_calls(count: int) -> None:
    budget = _current.get()
    if budget is not None:
        budget.release(count)


def reserve_model_call(*, optional: bool = False) -> bool:
    budget = _current.get()
    if budget is None or budget.reserve():
        return True
    if optional:
        return False
    raise ModelCallBudgetExceeded("Model-call budget exhausted")
