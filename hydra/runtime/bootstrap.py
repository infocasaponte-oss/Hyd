# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.core.native_bootstrap."""
import sys

from hydra.core import native_bootstrap as _implementation
from hydra.core.native_bootstrap import BootstrapResult, bootstrap_runtime

__all__ = ['BootstrapResult', 'bootstrap_runtime']
sys.modules[__name__] = _implementation
