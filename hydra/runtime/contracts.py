# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.core.native_contracts."""
import sys
from hydra.core import native_contracts as _implementation
from hydra.core.native_contracts import TaskStatus, TaskType, CognitiveBudget, HydraTask, Route, HydraResult

__all__ = ['TaskStatus', 'TaskType', 'CognitiveBudget', 'HydraTask', 'Route', 'HydraResult']
sys.modules[__name__] = _implementation
