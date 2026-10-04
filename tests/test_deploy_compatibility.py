# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Old deployment imports preserve type identity, schemas and probe patching."""
from hydra.deploy import deployment_evidence, health_gate
from hydra.runtime import deployment_evidence as legacy_evidence
from hydra.runtime import health_gate as legacy_health


def test_promotion_types_and_functions_are_identical():
    for name in legacy_evidence.__all__:
        assert getattr(legacy_evidence, name) is getattr(deployment_evidence, name)
    from dataclasses import fields
    assert fields(legacy_evidence.ShadowEvidence) == fields(deployment_evidence.ShadowEvidence)
    assert fields(legacy_evidence.CanaryEvidence) == fields(deployment_evidence.CanaryEvidence)


def test_probe_module_identity_preserves_monkeypatching(monkeypatch):
    assert legacy_health is health_gate
    def probe():
        return 42
    monkeypatch.setattr(legacy_health, 'monotonic', probe)
    assert health_gate.monotonic() == 42
