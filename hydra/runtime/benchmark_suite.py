# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.model_factory.physical.benchmark_suite``."""
from __future__ import annotations

from hydra.model_factory.physical.benchmark_suite import (  # noqa: F401
    BenchmarkCase,
    BenchmarkSuite,
    RTX3060TI_ALPHA_SUITE,
)

__all__ = ['BenchmarkCase', 'BenchmarkSuite', 'RTX3060TI_ALPHA_SUITE']
