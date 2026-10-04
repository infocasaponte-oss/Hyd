# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.core.outbox."""
import sys
from hydra.core import outbox as _implementation
from hydra.core.outbox import (
    OutboxMessage,
    TransactionalOutbox,
)

__all__ = ['OutboxMessage', 'TransactionalOutbox']
sys.modules[__name__] = _implementation
