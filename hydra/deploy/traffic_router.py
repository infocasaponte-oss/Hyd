# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from hydra.deploy.deployment import Deployment, DeploymentState
from hydra.deploy.deployment_registry import DeploymentRegistry
from hydra.deploy.runtime_health import RuntimeHealth


@dataclass(frozen=True)
class TrafficDecision:
    primary: Deployment
    shadow: Deployment | None = None
    canary: Deployment | None = None


class TrafficRouter:
    def __init__(
        self,
        registry: DeploymentRegistry,
        health: RuntimeHealth,
        *,
        canary_percent: int = 5,
    ):
        if not 0 <= canary_percent <= 100:
            raise ValueError("canary_percent must be between 0 and 100")
        self.registry = registry
        self.health = health
        self.canary_percent = canary_percent

    def _healthy(self, deployment: Deployment) -> bool:
        return self.health.available(str(deployment.variant_id))

    def _bucket(self, trace_id: str) -> int:
        digest = hashlib.sha256(trace_id.encode()).digest()
        return int.from_bytes(digest[:4], "big") % 100

    def route(self, capability: str, trace_id: str) -> TrafficDecision:
        active = [
            item for item in self.registry.deployments.values()
            if item.state == DeploymentState.ACTIVE
            and capability in item.capabilities
            and self._healthy(item)
        ]
        if not active:
            fallback = [
                item for item in self.registry.deployments.values()
                if item.state == DeploymentState.DEPRECATED
                and capability in item.capabilities
                and self._healthy(item)
            ]
            if not fallback:
                raise LookupError(f"No healthy deployment for {capability}")
            primary = max(fallback, key=lambda item: item.generation)
        else:
            primary = max(active, key=lambda item: item.generation)

        shadows = [
            item for item in self.registry.deployments.values()
            if item.state == DeploymentState.SHADOW
            and capability in item.capabilities
            and self._healthy(item)
        ]
        canaries = [
            item for item in self.registry.deployments.values()
            if item.state == DeploymentState.CANARY
            and capability in item.capabilities
            and self._healthy(item)
        ]
        shadow = max(shadows, key=lambda item: item.generation) if shadows else None
        canary = None
        if canaries and self._bucket(trace_id) < self.canary_percent:
            canary = max(canaries, key=lambda item: item.generation)

        return TrafficDecision(primary=primary, shadow=shadow, canary=canary)
