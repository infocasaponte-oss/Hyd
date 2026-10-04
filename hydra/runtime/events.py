# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.core.durable_events."""
import sys
from hydra.core import durable_events as _implementation
from hydra.core.durable_events import (
    EventEnvelope,
    IntegrityReport,
    _event_body,
    _Duplicate,
    JsonlEventStore,
)

__all__ = ['EventEnvelope', 'IntegrityReport', '_event_body', '_Duplicate', 'JsonlEventStore']
sys.modules[__name__] = _implementation
