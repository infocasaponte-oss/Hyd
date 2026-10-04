# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Re-export (F4k): moved to ``hydra.model_factory.physical.process_supervisor``."""
from __future__ import annotations

from hydra.model_factory.physical.process_supervisor import (  # noqa: F401
    ManagedProcess,
    ProcessSupervisor,
)

__all__ = ['ManagedProcess', 'ProcessSupervisor']
