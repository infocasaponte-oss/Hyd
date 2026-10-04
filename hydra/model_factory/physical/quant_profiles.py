# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Quantisation and serving profiles per GPU."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuantProfile:
    name: str
    quantization: str
    context: int
    parallel: int
    kv_k: str
    kv_v: str
    gpu_layers: int


RTX3060TI_PROFILES = (
    QuantProfile("quality", "Q5_K_M", 4096, 1, "q8_0", "q8_0", 99),
    QuantProfile("balanced", "Q4_K_M", 8192, 1, "q8_0", "q8_0", 99),
    QuantProfile("context", "Q4_K_M", 12288, 1, "q8_0", "q8_0", 99),
)


def profiles_for(gpu_name: str, vram_mb: int) -> tuple[QuantProfile, ...]:
    if "3060 Ti" in gpu_name and vram_mb >= 7500:
        return RTX3060TI_PROFILES
    return (QuantProfile("safe", "Q4_K_M", 4096, 1, "q8_0", "q8_0", 99),)
