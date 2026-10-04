# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.core.outbox_dispatcher."""
import sys
from hydra.core import outbox_dispatcher as _implementation
from hydra.core.outbox_dispatcher import (
    DispatchResult,
    OutboxDispatcher,
)

__all__ = ['DispatchResult', 'OutboxDispatcher']
sys.modules[__name__] = _implementation
