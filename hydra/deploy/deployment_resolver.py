# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass

from hydra.deploy.deployment import Deployment
from hydra.deploy.deployment_registry import DeploymentRegistry


@dataclass
class DeploymentResolver:
    registry: DeploymentRegistry

    def resolve(self, capability: str) -> Deployment:
        deployment = self.registry.active_for(capability)
        if capability not in deployment.capabilities:
            raise LookupError(f"Deployment does not provide {capability}")
        return deployment
