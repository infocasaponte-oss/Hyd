# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compatibility module alias for hydra.deploy.deployment_store."""
import sys
from hydra.deploy import deployment_store as _implementation
from hydra.deploy.deployment_store import (
    log,
    T,
    DeploymentStore,
)

__all__ = ['log', 'T', 'DeploymentStore']
sys.modules[__name__] = _implementation
