# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.core.outbox_recovery."""
import sys

from hydra.core import outbox_recovery as _implementation
from hydra.core.outbox_recovery import RecoveryResult, recover_pending

__all__ = ['RecoveryResult', 'recover_pending']
sys.modules[__name__] = _implementation
