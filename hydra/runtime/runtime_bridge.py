# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.deploy.bridge."""
import sys
from hydra.deploy import bridge as _implementation
from hydra.deploy.bridge import (
    RuntimeBridge,
)

__all__ = ['RuntimeBridge']
sys.modules[__name__] = _implementation
