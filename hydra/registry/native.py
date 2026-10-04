# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    model_id: str
    capabilities: frozenset[str]
    local: bool = True
    enabled: bool = True
    quality: float = 0.5
    latency: float = 0.5
    cost: float = 0.0


class NoModelAvailable(LookupError):
    pass


class ModelRegistry:
    def __init__(self, models: list[ModelProfile] | None = None):
        self.models = models or [
            ModelProfile(
                model_id="local-main",
                capabilities=frozenset(
                    {"chat.multilingual", "language.translate", "reasoning.general"}
                ),
                quality=0.70,
                latency=0.65,
            )
        ]

    def resolve(self, capability: str, *, local_only: bool = True) -> ModelProfile:
        candidates = [
            m for m in self.models
            if m.enabled
            and capability in m.capabilities
            and (m.local or not local_only)
        ]
        if not candidates:
            raise NoModelAvailable(capability)
        return max(candidates, key=lambda m: (m.quality * 0.7) - (m.latency * 0.2) - (m.cost * 0.1))
