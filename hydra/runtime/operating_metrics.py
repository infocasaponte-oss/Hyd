# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4c): moved to ``hydra.observability.operating``."""
from __future__ import annotations

from hydra.observability.operating import (  # noqa: F401
    OperatingMetrics,
    collect_operating_metrics,
)

__all__ = ["OperatingMetrics", "collect_operating_metrics"]
