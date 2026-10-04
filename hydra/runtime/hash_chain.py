# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.core.hash_chain."""
import sys
from hydra.core import hash_chain as _implementation
from hydra.core.hash_chain import (
    _PROCESS_LOCKS,
    _PROCESS_LOCKS_GUARD,
    lock_for,
    canonical_hash,
)

__all__ = ['_PROCESS_LOCKS', '_PROCESS_LOCKS_GUARD', 'lock_for', 'canonical_hash']
sys.modules[__name__] = _implementation
