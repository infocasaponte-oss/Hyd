# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.model_factory.physical.promotion_gate``."""
from __future__ import annotations

from hydra.model_factory.physical.promotion_gate import (  # noqa: F401
    PromotionPolicy,
    apply_promotion_gate,
)

__all__ = ['PromotionPolicy', 'apply_promotion_gate']
