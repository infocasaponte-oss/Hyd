# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.edge.native_translation."""
import sys

from hydra.edge import native_translation as _implementation
from hydra.edge.native_translation import GlossaryStore, TranslationService, split_text

__all__ = ["GlossaryStore", "TranslationService", "split_text"]
sys.modules[__name__] = _implementation
