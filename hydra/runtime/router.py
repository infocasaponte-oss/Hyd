# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.router.native."""
import sys
from hydra.router import native as _implementation
from hydra.router.native import CapabilityRouter

__all__ = ['CapabilityRouter']
sys.modules[__name__] = _implementation
