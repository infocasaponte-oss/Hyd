# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass, field

from hydra.deploy.deployment import Deployment, DeploymentState


@dataclass
class DeploymentRegistry:
    deployments: dict[str, Deployment] = field(default_factory=dict)

    @staticmethod
    def _active_capabilities(deployment: Deployment) -> set[str]:
        raw = deployment.metadata.get("active_capabilities")
        if raw is None:
            if deployment.state == DeploymentState.ACTIVE:
                return set(deployment.capabilities)
            return set()
        return set(raw)

    @staticmethod
    def _set_active_capabilities(
        deployment: Deployment,
        capabilities: set[str],
    ) -> None:
        deployment.metadata["active_capabilities"] = sorted(capabilities)

    def add(self, deployment: Deployment) -> None:
        key = str(deployment.variant_id)
        if key in self.deployments:
            raise ValueError("Deployment already registered")
        if deployment.state == DeploymentState.ACTIVE:
            self._set_active_capabilities(
                deployment,
                self._active_capabilities(deployment),
            )
        self.deployments[key] = deployment

    def active_for(self, capability: str) -> Deployment:
        matches = [
            item
            for item in self.deployments.values()
            if item.state == DeploymentState.ACTIVE
            and capability in self._active_capabilities(item)
        ]
        if not matches:
            raise LookupError(f"No ACTIVE deployment for {capability}")
        return max(matches, key=lambda item: item.generation)

    def activate(self, variant_id: str) -> Deployment:
        incoming = self.deployments[variant_id]
        if incoming.state != DeploymentState.CANARY:
            raise ValueError("Only CANARY deployment can become ACTIVE")

        for current in self.deployments.values():
            if current.state != DeploymentState.ACTIVE:
                continue
            active = self._active_capabilities(current)
            overlap = active & incoming.capabilities
            if not overlap:
                continue
            remaining = active - overlap
            self._set_active_capabilities(current, remaining)
            if not remaining:
                current.transition(DeploymentState.DEPRECATED)

        incoming.transition(DeploymentState.ACTIVE)
        self._set_active_capabilities(incoming, set(incoming.capabilities))
        return incoming

    def rollback(self, capability: str) -> Deployment:
        current = self.active_for(capability)
        previous = [
            item
            for item in self.deployments.values()
            if item is not current
            and capability in item.capabilities
            and item.generation < current.generation
            and item.state in {DeploymentState.ACTIVE, DeploymentState.DEPRECATED}
        ]
        if not previous:
            raise LookupError("No rollback deployment available")

        target = max(previous, key=lambda item: item.generation)

        current_active = self._active_capabilities(current)
        current_active.discard(capability)
        self._set_active_capabilities(current, current_active)
        if not current_active:
            current.transition(DeploymentState.DEPRECATED)

        if target.state == DeploymentState.DEPRECATED:
            target.transition(DeploymentState.ACTIVE)
        target_active = self._active_capabilities(target)
        target_active.add(capability)
        self._set_active_capabilities(target, target_active)
        return target
