# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.core.native_kernel."""
import sys

from hydra.core import native_kernel as _implementation
from hydra.core.native_kernel import HydraKernel

__all__ = ['HydraKernel']
sys.modules[__name__] = _implementation
