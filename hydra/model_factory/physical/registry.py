# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""In-memory registry of promoted physical variants."""
from __future__ import annotations

from dataclasses import dataclass, field

from hydra.model_factory.contracts import BuildState, ModelVariant


@dataclass
class PhysicalModelRegistry:
    _variants: dict[str, ModelVariant] = field(default_factory=dict)

    def register(self, variant: ModelVariant) -> None:
        if variant.state != BuildState.PROMOTED:
            raise ValueError("Only PROMOTED physical variants may enter active registry")
        self._variants[str(variant.variant_id)] = variant

    def resolve(self, *, quantization: str | None = None) -> ModelVariant:
        candidates = list(self._variants.values())
        if quantization:
            candidates = [v for v in candidates if v.quantization == quantization]
        if not candidates:
            raise LookupError("No promoted physical model variant available")
        return candidates[0]
