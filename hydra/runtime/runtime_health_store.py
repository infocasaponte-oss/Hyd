# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.deploy.runtime_health_store."""
import sys
from hydra.deploy import runtime_health_store as _implementation
from hydra.deploy.runtime_health_store import (
    RuntimeHealthStore,
)

__all__ = ['RuntimeHealthStore']
sys.modules[__name__] = _implementation
