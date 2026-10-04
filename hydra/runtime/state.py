# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.core.native_state."""
import sys

from hydra.core import native_state as _implementation
from hydra.core.native_state import InvalidTransition, validate_transition, _ALLOWED

__all__ = ['InvalidTransition', 'validate_transition', '_ALLOWED']
sys.modules[__name__] = _implementation
