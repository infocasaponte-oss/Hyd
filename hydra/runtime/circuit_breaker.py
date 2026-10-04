# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility re-export; the implementation lives in :mod:`hydra.registry.circuit_breaker`."""
from hydra.registry.circuit_breaker import Breaker as CircuitBreaker
from hydra.registry.circuit_breaker import CircuitState

__all__ = ["CircuitBreaker", "CircuitState"]
