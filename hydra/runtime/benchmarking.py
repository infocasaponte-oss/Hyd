# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.model_factory.physical.benchmark``."""
from __future__ import annotations

from hydra.model_factory.physical.benchmark import (  # noqa: F401
    BenchmarkResult,
    score_benchmark,
    select_variant,
)

__all__ = ['BenchmarkResult', 'score_benchmark', 'select_variant']
