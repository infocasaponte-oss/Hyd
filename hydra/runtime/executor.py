# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.scheduler.native_executor."""
import sys
from hydra.scheduler import native_executor as _implementation
from hydra.scheduler.native_executor import (
    UnsafePlan,
    ExecutionOutput,
    Executor,
)

__all__ = ['UnsafePlan', 'ExecutionOutput', 'Executor']
sys.modules[__name__] = _implementation
