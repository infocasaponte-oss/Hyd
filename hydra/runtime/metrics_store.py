# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4c): moved to ``hydra.observability.operating_store``."""
from __future__ import annotations

from hydra.observability.operating_store import (  # noqa: F401
    OperatingMetricsStore,
)

__all__ = ["OperatingMetricsStore"]
