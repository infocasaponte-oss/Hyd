# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from hydra.model_factory.contracts import BuildState, ModelVariant


class DeploymentState(StrEnum):
    CANDIDATE = "candidate"
    SHADOW = "shadow"
    CANARY = "canary"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


_ALLOWED = {
    DeploymentState.CANDIDATE: {DeploymentState.SHADOW, DeploymentState.RETIRED},
    DeploymentState.SHADOW: {DeploymentState.CANARY, DeploymentState.RETIRED},
    DeploymentState.CANARY: {DeploymentState.ACTIVE, DeploymentState.RETIRED},
    DeploymentState.ACTIVE: {DeploymentState.DEPRECATED},
    DeploymentState.DEPRECATED: {DeploymentState.ACTIVE, DeploymentState.RETIRED},
    DeploymentState.RETIRED: set(),
}


@dataclass
class Deployment:
    variant: ModelVariant
    capabilities: set[str]
    state: DeploymentState = DeploymentState.CANDIDATE
    generation: int = 0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.variant.state != BuildState.PROMOTED:
            raise ValueError("Deployment requires a PROMOTED physical variant")

    @property
    def variant_id(self) -> UUID:
        return self.variant.variant_id

    def transition(self, target: DeploymentState) -> None:
        if target not in _ALLOWED[self.state]:
            raise ValueError(f"Invalid deployment transition: {self.state} -> {target}")
        self.state = target
