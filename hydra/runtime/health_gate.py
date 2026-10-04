# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility export; implementation lives in hydra.deploy.health_gate."""
import sys
from hydra.deploy import health_gate as _implementation
from hydra.deploy.health_gate import wait_for_health

__all__ = ["wait_for_health"]
# Preserve module identity so existing probe monkeypatches affect its globals.
sys.modules[__name__] = _implementation
