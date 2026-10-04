# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass, field

from hydra.registry.circuit_breaker import Breaker as CircuitBreaker
from hydra.deploy.runtime_health_store import RuntimeHealthStore


@dataclass
class RuntimeHealth:
    store: RuntimeHealthStore | None = None
    breakers: dict[str, CircuitBreaker] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.store is None:
            return
        restored = self.store.load()
        restored.update(self.breakers)
        self.breakers = restored

    def breaker_for(self, variant_id: str) -> CircuitBreaker:
        return self.breakers.setdefault(variant_id, CircuitBreaker())

    def available(self, variant_id: str) -> bool:
        breaker = self.breaker_for(variant_id)
        previous_state = breaker.state
        allowed = breaker.allow()
        if self.store is not None and breaker.state != previous_state:
            self.store.save(variant_id, breaker)
        return allowed

    def success(self, variant_id: str) -> None:
        breaker = self.breaker_for(variant_id)
        breaker.record_success()
        if self.store is not None:
            self.store.save(variant_id, breaker)

    def failure(self, variant_id: str) -> None:
        breaker = self.breaker_for(variant_id)
        breaker.record_failure()
        if self.store is not None:
            self.store.save(variant_id, breaker)
