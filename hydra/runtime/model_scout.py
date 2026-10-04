# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.model_factory.model_scout."""
import sys
from hydra.model_factory import model_scout as _implementation
from hydra.model_factory.model_scout import (
    ModelArtifact,
    _sha256,
    HashCache,
    inspect_model_artifact,
    scan_models,
)

__all__ = ['ModelArtifact', '_sha256', 'HashCache', 'inspect_model_artifact', 'scan_models']
sys.modules[__name__] = _implementation
