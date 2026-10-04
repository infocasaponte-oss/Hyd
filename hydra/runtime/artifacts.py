# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.artifacts.task_store."""
import sys
from hydra.artifacts import task_store as _implementation
from hydra.artifacts.task_store import (
    ArtifactRecord,
    ArtifactStore,
)

__all__ = ['ArtifactRecord', 'ArtifactStore']
sys.modules[__name__] = _implementation
