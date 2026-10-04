# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.corpus.artifact_candidates."""
import sys
from hydra.corpus import artifact_candidates as _implementation
from hydra.corpus.artifact_candidates import (
    CorpusStatus,
    QualityTier,
    RightsDeclaration,
    CorpusRecord,
    CorpusGate,
    CorpusIndex,
    _Duplicate,
    CorpusStore,
)

__all__ = ['CorpusStatus', 'QualityTier', 'RightsDeclaration', 'CorpusRecord', 'CorpusGate', 'CorpusIndex', '_Duplicate', 'CorpusStore']
sys.modules[__name__] = _implementation
