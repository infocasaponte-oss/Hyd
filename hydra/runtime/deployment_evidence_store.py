# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.deploy.deployment_evidence_store."""
import sys
from hydra.deploy import deployment_evidence_store as _implementation
from hydra.deploy.deployment_evidence_store import (
    DeploymentEvidenceStore,
)

__all__ = ['DeploymentEvidenceStore']
sys.modules[__name__] = _implementation
