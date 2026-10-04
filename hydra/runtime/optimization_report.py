# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.model_factory.physical.optimization_report``."""
from __future__ import annotations

from hydra.model_factory.physical.optimization_report import (  # noqa: F401
    OptimizationReport,
    OptimizationReportStore,
)

__all__ = ['OptimizationReport', 'OptimizationReportStore']
