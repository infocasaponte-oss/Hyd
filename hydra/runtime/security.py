# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.api.native_access."""
import sys

from hydra.api import native_access as _implementation
from hydra.api.native_access import (
    SecurityConfig,
    _provided_token,
    _matches,
    require_api_access,
    require_admin_access,
)

__all__ = ['SecurityConfig', '_provided_token', '_matches', 'require_api_access', 'require_admin_access']
sys.modules[__name__] = _implementation
