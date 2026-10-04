# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.deploy.executor."""
import sys
from hydra.deploy import executor as _implementation
from hydra.deploy.executor import (
    InferenceCall,
    RuntimeExecution,
    _elapsed_ms,
    RuntimeExecutor,
)

__all__ = ['InferenceCall', 'RuntimeExecution', '_elapsed_ms', 'RuntimeExecutor']
sys.modules[__name__] = _implementation
