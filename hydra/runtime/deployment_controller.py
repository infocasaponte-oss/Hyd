# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.deploy.deployment_controller."""
import sys
from hydra.deploy import deployment_controller as _implementation
from hydra.deploy.deployment_controller import (
    log,
    SHADOW_STARTED_AT,
    CANARY_STARTED_AT,
    SHADOW_EVIDENCE_SEQ,
    CANARY_EVIDENCE_SEQ,
    LEGACY_OFFSETS,
    EvidenceRejected,
    _now,
    DeploymentController,
)

__all__ = ['log', 'SHADOW_STARTED_AT', 'CANARY_STARTED_AT', 'SHADOW_EVIDENCE_SEQ', 'CANARY_EVIDENCE_SEQ', 'LEGACY_OFFSETS', 'EvidenceRejected', '_now', 'DeploymentController']
sys.modules[__name__] = _implementation
