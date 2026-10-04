# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.audit.access."""
import sys

from hydra.audit import access as _implementation
from hydra.audit.access import (
    SecurityAudit,
)

__all__ = ['SecurityAudit']
sys.modules[__name__] = _implementation
