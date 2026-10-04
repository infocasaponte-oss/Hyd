# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.model_factory.physical.pareto``."""
from __future__ import annotations

from hydra.model_factory.physical.pareto import (  # noqa: F401
    dominates,
    pareto_frontier,
)

__all__ = ['dominates', 'pareto_frontier']
