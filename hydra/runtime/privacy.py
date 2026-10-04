# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.corpus.artifact_privacy."""
import sys
from hydra.corpus import artifact_privacy as _implementation
from hydra.corpus.artifact_privacy import (
    _GATE,
    _finding_types,
    PrivacyScanner,
    PrivacyScanResult,
    PrivacyScanStatus,
)

__all__ = ['_GATE', '_finding_types', 'PrivacyScanner', 'PrivacyScanResult', 'PrivacyScanStatus']
sys.modules[__name__] = _implementation
