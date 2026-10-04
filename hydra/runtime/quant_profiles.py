# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.model_factory.physical.quant_profiles``."""
from __future__ import annotations

from hydra.model_factory.physical.quant_profiles import (  # noqa: F401
    QuantProfile,
    RTX3060TI_PROFILES,
    profiles_for,
)

__all__ = ['QuantProfile', 'RTX3060TI_PROFILES', 'profiles_for']
