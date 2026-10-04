# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""AutoQuant summary of measured candidates for a hardware target."""
from __future__ import annotations

from dataclasses import dataclass

from hydra.model_factory.physical.benchmark import BenchmarkResult, select_variant
from hydra.model_factory.physical.optimization_report import OptimizationReport
from hydra.model_factory.physical.pareto import pareto_frontier


@dataclass(frozen=True)
class HardwareTarget:
    name: str
    vram_mb: int


class AutoQuant:
    def summarize(
        self,
        *,
        hardware: HardwareTarget,
        results: list[BenchmarkResult],
        measured: bool,
    ) -> OptimizationReport:
        frontier = pareto_frontier(results, hardware.vram_mb)
        selected = None
        if measured and frontier:
            selected = select_variant(frontier, hardware.vram_mb).variant_id
        return OptimizationReport(
            hardware_name=hardware.name,
            hardware_vram_mb=hardware.vram_mb,
            measured=measured,
            candidates=results,
            pareto_variant_ids=[item.variant_id for item in frontier],
            selected_variant_id=selected,
        )
