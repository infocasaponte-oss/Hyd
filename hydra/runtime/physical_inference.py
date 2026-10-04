# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.providers.physical."""
import sys
from hydra.providers import physical as _implementation
from hydra.providers.physical import (
    _LOCAL_HOSTS,
    PhysicalInferenceUnavailable,
    PhysicalInferenceClient,
)

__all__ = ['_LOCAL_HOSTS', 'PhysicalInferenceUnavailable', 'PhysicalInferenceClient']
sys.modules[__name__] = _implementation
