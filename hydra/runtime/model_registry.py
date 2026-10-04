# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.registry.native."""
import sys
from hydra.registry import native as _implementation
from hydra.registry.native import (
    ModelProfile,
    NoModelAvailable,
    ModelRegistry,
)

__all__ = ['ModelProfile', 'NoModelAvailable', 'ModelRegistry']
sys.modules[__name__] = _implementation
