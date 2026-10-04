# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.core.outbox_metrics."""
import sys
from hydra.core import outbox_metrics as _implementation
from hydra.core.outbox_metrics import (
    OutboxMetrics,
    collect_outbox_metrics,
)

__all__ = ['OutboxMetrics', 'collect_outbox_metrics']
sys.modules[__name__] = _implementation
