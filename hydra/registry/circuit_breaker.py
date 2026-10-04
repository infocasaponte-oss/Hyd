# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Circuit breakers: a single-target state machine (:class:`Breaker`) and a per-model
registry (:class:`CircuitBreaker`) that temporarily disables models that keep failing
(OOM, timeouts, crashes)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class Breaker:
    """CLOSED -> OPEN after ``failure_threshold`` failures; OPEN -> HALF_OPEN after
    ``recovery_seconds``; a failure while HALF_OPEN reopens immediately."""

    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    opened_at: float | None = None

    @property
    def open(self) -> bool:
        return self.state == CircuitState.OPEN

    def allow(self) -> bool:
        if self.state != CircuitState.OPEN:
            return True
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.recovery_seconds:
            self.state = CircuitState.HALF_OPEN
            return True
        return False

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self.state = CircuitState.CLOSED

    def record_failure(self, fatal: bool = False) -> None:
        self.failures += 1
        if fatal or self.state == CircuitState.HALF_OPEN or self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = time.monotonic()


class CircuitBreaker:
    def __init__(self, max_failures: int = 5, cooldown_s: float = 60, slow_ms: float = 20_000) -> None:
        self.max_failures = max_failures
        self.cooldown_s = cooldown_s
        self.slow_ms = slow_ms
        self.models: dict[str, Breaker] = {}

    def _state(self, model_id: str) -> Breaker:
        return self.models.setdefault(model_id, Breaker(self.max_failures, self.cooldown_s))

    def register_failure(self, model_id: str, fatal: bool = False) -> None:
        self._state(model_id).record_failure(fatal)

    def register_success(self, model_id: str, latency_ms: float) -> None:
        if latency_ms > self.slow_ms:
            self.register_failure(model_id)
            return
        self._state(model_id).record_success()

    def available(self, model_id: str) -> bool:
        # half-open: allow one trial, a new failure reopens immediately
        return self._state(model_id).allow()
