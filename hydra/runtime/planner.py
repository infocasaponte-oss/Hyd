# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.scheduler.native."""
import sys
from hydra.scheduler import native as _implementation
from hydra.scheduler.native import StepKind, PlanStep, ExecutionPlan, Planner

__all__ = ['StepKind', 'PlanStep', 'ExecutionPlan', 'Planner']
sys.modules[__name__] = _implementation
