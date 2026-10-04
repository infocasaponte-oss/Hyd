# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import httpx
import pytest
from hydra.core.contracts import HydraRequest, Message, DecisionObservation
from hydra.providers.decision import LocalSystemOneProvider
from hydra.router.decision_authority import DecisionAuthority
from hydra.router.decision_contract import CRITERIA
from hydra.router.observer import DecisionObserver
from hydra.training.calibrator import TemperatureCalibrator


def evidence():
    return dict(model="kev-latest", independent_test=True, complete=True, accuracy=.98,
                accuracy_wilson_lower_95=.94, coverage=.99, ece_10_bins=.03,
                calibration_model_bound=True, model_revision="candidate")


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), True, -1, 1.1])
def test_invalid_metrics_never_enable_control(bad):
    report = evidence()
    report["accuracy"] = bad
    assert not DecisionAuthority.from_evidence(report, "kev-latest").enabled


def test_known_regression_cannot_enable_authority_or_critical_actions():
    report = evidence()
    report["independent_test"] = False
    assert not DecisionAuthority.from_evidence(report, "kev-latest").enabled
    authority = DecisionAuthority.from_evidence(evidence(), "kev-latest")
    for label in ("tool_use", "security", "privacy", "high_risk_review", "abstain"):
        observed = DecisionObservation(model="kev-latest", status="observed", selected=label, confidence=1)
        assert authority.task_hint(observed) is None


async def test_checkpoint_bound_shadow_rejects_replaced_checkpoint():
    calls = []
    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, json={"models": [{"name": "kev-latest", "run": "replacement"}]})
    provider = LocalSystemOneProvider(transport=httpx.MockTransport(handler))
    observer = DecisionObserver(provider, calibrator=TemperatureCalibrator(model_run="candidate"), criteria=CRITERIA)
    result = await observer.observe(HydraRequest(messages=[Message(role="user", content="Saluda cordialmente.")]))
    assert result.status == "error" and calls == ["/v1/models"]
    await observer.close()
