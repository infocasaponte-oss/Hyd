# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.deploy.readiness."""
import sys
from hydra.deploy import readiness as _implementation
from hydra.deploy.readiness import (
    ReadinessStatus,
    evaluate_readiness,
)

__all__ = ['ReadinessStatus', 'evaluate_readiness']
sys.modules[__name__] = _implementation
