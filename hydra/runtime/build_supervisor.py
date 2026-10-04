# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.model_factory.physical.build_supervisor``."""
from __future__ import annotations

from hydra.model_factory.physical.build_supervisor import (  # noqa: F401
    BuildResult,
    BuildSupervisor,
)

__all__ = ['BuildResult', 'BuildSupervisor']
