# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""SHADOW -> CANARY -> ACTIVE promotions gated by evidence.

The evidence is measured by the server from live traffic (``RuntimeEvidenceStore``), counted only
from the records written after the deployment entered the phase being judged (log sequence number). Callers may still pass explicit
evidence in-process (offline evaluation, tests), but the admin API never accepts it from a client."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from hydra.deploy.deployment import Deployment, DeploymentState
from hydra.deploy.deployment_evidence import (
    CanaryEvidence,
    DeploymentPolicy,
    ShadowEvidence,
    canary_passes,
    shadow_passes,
)
from hydra.deploy.deployment_evidence_store import DeploymentEvidenceStore
from hydra.deploy.deployment_registry import DeploymentRegistry
from hydra.deploy.runtime_evidence import RuntimeEvidenceStore

log = logging.getLogger("hydra.runtime.deployments")

SHADOW_STARTED_AT = "shadow_started_at"
CANARY_STARTED_AT = "canary_started_at"
SHADOW_EVIDENCE_SEQ = "shadow_evidence_seq"
CANARY_EVIDENCE_SEQ = "canary_evidence_seq"
# Phase starts recorded as byte offsets in runtime-evidence.jsonl before the evidence log moved to
# sequence numbers; ``migrate_phase_starts`` converts them once.
LEGACY_OFFSETS = {SHADOW_EVIDENCE_SEQ: "shadow_evidence_offset", CANARY_EVIDENCE_SEQ: "canary_evidence_offset"}


class EvidenceRejected(ValueError):
    """The measured evidence does not satisfy the deployment policy."""

    def __init__(self, message: str, evidence: ShadowEvidence | CanaryEvidence):
        super().__init__(message)
        self.evidence = evidence


def _now() -> str:
    return datetime.now(UTC).isoformat()


class DeploymentController:
    def __init__(
        self,
        registry: DeploymentRegistry,
        policy: DeploymentPolicy | None = None,
        evidence_store: DeploymentEvidenceStore | None = None,
        runtime_evidence: RuntimeEvidenceStore | None = None,
    ):
        self.registry = registry
        self.policy = policy or DeploymentPolicy()
        self.evidence_store = evidence_store
        self.runtime_evidence = runtime_evidence

    def begin_shadow(self, deployment: Deployment) -> None:
        deployment.transition(DeploymentState.SHADOW)
        self._mark_phase(deployment, SHADOW_STARTED_AT, SHADOW_EVIDENCE_SEQ)

    def measure_shadow(self, deployment: Deployment) -> ShadowEvidence:
        return self._store().shadow_evidence(str(deployment.variant_id), self._phase_start(deployment, SHADOW_EVIDENCE_SEQ))

    def measure_canary(self, deployment: Deployment) -> CanaryEvidence:
        return self._store().canary_evidence(str(deployment.variant_id), self._phase_start(deployment, CANARY_EVIDENCE_SEQ))

    def _mark_phase(self, deployment: Deployment, started_key: str, seq_key: str) -> None:
        deployment.metadata[started_key] = _now()
        deployment.metadata.pop(LEGACY_OFFSETS[seq_key], None)
        if self.runtime_evidence is not None:
            deployment.metadata[seq_key] = self.runtime_evidence.position()

    def _phase_start(self, deployment: Deployment, seq_key: str) -> int:
        if seq_key not in deployment.metadata and LEGACY_OFFSETS[seq_key] in deployment.metadata:
            self._convert_legacy(deployment, seq_key)
        return int(deployment.metadata.get(seq_key, 0))

    def _convert_legacy(self, deployment: Deployment, seq_key: str) -> bool:
        """Byte offset -> sequence number. If the old evidence file is gone, the phase restarts now:
        fewer samples, never evidence that cannot be attributed to the phase."""
        offset = int(deployment.metadata.pop(LEGACY_OFFSETS[seq_key]))
        store = self._store()
        seq = store.seq_at_byte_offset(offset)
        if seq is None:
            log.warning("deployment %s: evidence file for its %s phase start is gone; counting from now",
                        deployment.variant_id, seq_key.split("_")[0])
            seq = store.position()
            deployment.metadata["evidence_restarted_at"] = _now()
        deployment.metadata[seq_key] = seq
        return True

    def migrate_phase_starts(self) -> int:
        """Convert legacy byte-offset phase starts of every deployment once; returns how many changed
        (the caller saves the registry when it is not zero)."""
        if self.runtime_evidence is None:
            return 0
        changed = 0
        for deployment in self.registry.deployments.values():
            for seq_key, legacy in LEGACY_OFFSETS.items():
                if legacy in deployment.metadata and seq_key not in deployment.metadata:
                    changed += self._convert_legacy(deployment, seq_key)
        return changed

    def approve_canary(
        self, deployment: Deployment, evidence: ShadowEvidence | None = None
    ) -> ShadowEvidence:
        if deployment.state != DeploymentState.SHADOW:
            raise ValueError("Deployment is not in SHADOW")
        evidence = evidence if evidence is not None else self.measure_shadow(deployment)
        if not shadow_passes(evidence, self.policy):
            raise EvidenceRejected("Shadow evidence did not pass deployment policy", evidence)
        deployment.metadata["shadow_samples"] = evidence.samples
        if self.evidence_store is not None:
            self.evidence_store.append_shadow(str(deployment.variant_id), evidence)
        deployment.transition(DeploymentState.CANARY)
        self._mark_phase(deployment, CANARY_STARTED_AT, CANARY_EVIDENCE_SEQ)
        return evidence

    def activate(
        self, deployment: Deployment, evidence: CanaryEvidence | None = None
    ) -> Deployment:
        if deployment.state != DeploymentState.CANARY:
            raise ValueError("Deployment is not in CANARY")
        evidence = evidence if evidence is not None else self.measure_canary(deployment)
        if not canary_passes(evidence, self.policy):
            raise EvidenceRejected("Canary evidence did not pass deployment policy", evidence)
        deployment.metadata["canary_requests"] = evidence.requests
        if self.evidence_store is not None:
            self.evidence_store.append_canary(str(deployment.variant_id), evidence)
        return self.registry.activate(str(deployment.variant_id))

    def _store(self) -> RuntimeEvidenceStore:
        if self.runtime_evidence is None:
            raise ValueError("No runtime evidence store: promotion evidence cannot be measured")
        return self.runtime_evidence
