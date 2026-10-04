# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.deploy.runtime_health."""
import sys
from hydra.deploy import runtime_health as _implementation
from hydra.deploy.runtime_health import (
    RuntimeHealth,
)

__all__ = ['RuntimeHealth']
sys.modules[__name__] = _implementation
