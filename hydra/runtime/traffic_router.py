# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.deploy.traffic_router."""
import sys
from hydra.deploy import traffic_router as _implementation
from hydra.deploy.traffic_router import (
    TrafficDecision,
    TrafficRouter,
)

__all__ = ['TrafficDecision', 'TrafficRouter']
sys.modules[__name__] = _implementation
