# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility export; implementation lives in hydra.deploy.deployment_evidence."""
from hydra.deploy.deployment_evidence import (
    ShadowEvidence,
    CanaryEvidence,
    DeploymentPolicy,
    shadow_passes,
    canary_passes,
)

__all__ = ['ShadowEvidence', 'CanaryEvidence', 'DeploymentPolicy', 'shadow_passes', 'canary_passes']
