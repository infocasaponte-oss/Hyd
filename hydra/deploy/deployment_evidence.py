# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShadowEvidence:
    samples: int
    agreement_rate: float
    error_rate: float


@dataclass(frozen=True)
class CanaryEvidence:
    requests: int
    error_rate: float
    p95_latency_ms: float


@dataclass(frozen=True)
class DeploymentPolicy:
    min_shadow_samples: int = 20
    min_shadow_agreement: float = 0.95
    max_shadow_error_rate: float = 0.01
    min_canary_requests: int = 20
    max_canary_error_rate: float = 0.01
    max_canary_p95_latency_ms: float = 5000.0


def shadow_passes(evidence: ShadowEvidence, policy: DeploymentPolicy) -> bool:
    return (
        evidence.samples >= policy.min_shadow_samples
        and evidence.agreement_rate >= policy.min_shadow_agreement
        and evidence.error_rate <= policy.max_shadow_error_rate
    )


def canary_passes(evidence: CanaryEvidence, policy: DeploymentPolicy) -> bool:
    return (
        evidence.requests >= policy.min_canary_requests
        and evidence.error_rate <= policy.max_canary_error_rate
        and evidence.p95_latency_ms <= policy.max_canary_p95_latency_ms
    )
