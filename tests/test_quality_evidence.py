# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hydra.model_factory.validator import QualityGate, GateThresholds
from hydra.evals.engine import CaseResult, EvalReport, SuiteResult


def evidence():
    return EvalReport(target="candidate", overall=1,
        suites={s: SuiteResult(suite=s,score=1,passed=1,total=1,mean_latency_ms=1)
                for s in ("coding","reasoning","structured","tool_use","hallucination")},
        cases=[CaseResult(id="ok",suite="coding",passed=True,score=1,latency_ms=1)])


async def test_configured_resource_limits_require_measurements():
    gate = QualityGate(SimpleNamespace(run_model=AsyncMock(return_value=evidence())),
                       thresholds=GateThresholds(max_memory_gb=8,max_ttft_ms=1000))
    result, _ = await gate.validate(SimpleNamespace(id="artifact"),SimpleNamespace())
    assert not result.approved
    assert "missing memory measurement" in result.reasons
    assert "missing TTFT measurement" in result.reasons


async def test_missing_suite_cannot_pass_with_perfect_other_scores():
    report = evidence()
    del report.suites["tool_use"]
    gate = QualityGate(SimpleNamespace(run_model=AsyncMock(return_value=report)))
    result, _ = await gate.validate(SimpleNamespace(id="artifact"),SimpleNamespace())
    assert not result.approved and "missing evaluation suite: tool_use" in result.reasons


def test_build_preflight_rejects_missing_source(tmp_path):
    from hydra.model_factory.build_hydra import validate_inputs
    with pytest.raises(ValueError, match="missing build inputs"):
        validate_inputs({"base_model":str(tmp_path),"corpus":str(tmp_path),
                         "llamacpp":str(tmp_path),"quantizer":str(tmp_path/"missing")})
