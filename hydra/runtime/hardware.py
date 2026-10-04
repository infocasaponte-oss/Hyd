# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility re-export; the implementation lives in :mod:`hydra.edge.profiles` (a superset:
same fields plus runtime, CUDA arch, GPU layers and recommended model class)."""
from hydra.edge.profiles import HardwareProfile, resolve_profile

__all__ = ["HardwareProfile", "resolve_profile"]
