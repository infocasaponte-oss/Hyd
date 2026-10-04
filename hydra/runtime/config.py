# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.core.native_config."""
import sys

from hydra.core import native_config as _implementation
from hydra.core.native_config import Settings, settings, _DOTENV, _env

__all__ = ["Settings", "settings", "_DOTENV", "_env"]
sys.modules[__name__] = _implementation
