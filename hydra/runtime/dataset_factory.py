# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.corpus.artifact_datasets."""
import sys
from hydra.corpus import artifact_datasets as _implementation
from hydra.corpus.artifact_datasets import DatasetManifest, DatasetFactory

__all__ = ['DatasetManifest', 'DatasetFactory']
sys.modules[__name__] = _implementation
