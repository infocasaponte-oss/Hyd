# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.runtime.deployment_evidence import CanaryEvidence, ShadowEvidence
from hydra.runtime.deployment_evidence_store import DeploymentEvidenceStore


def test_deployment_evidence_survives_store_reopen(tmp_path):
    path = tmp_path / "hydra.db"
    store = DeploymentEvidenceStore(path)
    store.append_shadow("variant-1", ShadowEvidence(20, 0.96, 0.0))
    store.append_canary("variant-1", CanaryEvidence(25, 0.0, 400.0))

    reopened = DeploymentEvidenceStore(path)
    assert reopened.latest_shadow("variant-1") == ShadowEvidence(20, 0.96, 0.0)
    assert reopened.latest_canary("variant-1") == CanaryEvidence(25, 0.0, 400.0)
