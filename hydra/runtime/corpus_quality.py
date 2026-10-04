# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.corpus.patch_quality."""
import sys
from hydra.corpus import patch_quality as _implementation
from hydra.corpus.patch_quality import verified_patch_quality

__all__ = ['verified_patch_quality']
sys.modules[__name__] = _implementation
