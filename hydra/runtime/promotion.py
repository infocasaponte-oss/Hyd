# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.model_factory.physical.promotion``."""
from __future__ import annotations

from hydra.model_factory.physical.promotion import (  # noqa: F401
    PromotionDenied,
    promote,
)

__all__ = ['PromotionDenied', 'promote']
