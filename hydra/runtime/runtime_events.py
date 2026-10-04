# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.deploy.events."""
import sys
from hydra.deploy import events as _implementation
from hydra.deploy.events import (
    RuntimeEventEmitter,
)

__all__ = ['RuntimeEventEmitter']
sys.modules[__name__] = _implementation
