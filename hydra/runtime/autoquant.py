# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.model_factory.physical.autoquant``."""
from __future__ import annotations

from hydra.model_factory.physical.autoquant import (  # noqa: F401
    AutoQuant,
    HardwareTarget,
)

__all__ = ['AutoQuant', 'HardwareTarget']
