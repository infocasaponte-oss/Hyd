# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.deploy.deployment_validation."""
import sys
from hydra.deploy import deployment_validation as _implementation
from hydra.deploy.deployment_validation import (
    DeploymentArtifactValidator,
)

__all__ = ['DeploymentArtifactValidator']
sys.modules[__name__] = _implementation
