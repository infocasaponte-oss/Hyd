# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.deploy.runtime_evidence."""
import sys
from hydra.deploy import runtime_evidence as _implementation
from hydra.deploy.runtime_evidence import (
    RuntimeEvidence,
    _sha256,
    p95,
    RuntimeEvidenceStore,
    _Tally,
    _fold_shadow,
    _fold_canary,
)

__all__ = ['RuntimeEvidence', '_sha256', 'p95', 'RuntimeEvidenceStore', '_Tally', '_fold_shadow', '_fold_canary']
sys.modules[__name__] = _implementation
