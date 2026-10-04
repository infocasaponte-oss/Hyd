# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest
from hydra.training.calibration import fit_temperature, metrics, risk_coverage


def test_temperature_fit_reduces_nll_of_overconfidence():
    rows = [[8, 0], [8, 0], [0, 8], [0, 8]]
    result = fit_temperature(rows, [0, 1, 1, 0])
    assert result["temperature"] > 1
    assert result["after"]["nll"] < result["before"]["nll"]
    assert not result["approved"]


def test_no_invalid_calibration():
    with pytest.raises(ValueError):
        metrics([[0, 1]], [3])
    with pytest.raises(ValueError):
        metrics([[float("nan"), 1]], [0])


def test_zero_coverage_does_not_claim_perfect_accuracy():
    curve = risk_coverage([[1, 0], [0, 1]], [0, 1])
    assert curve[0]["coverage"] == 1
    assert curve[-1]["coverage"] == 0
    assert curve[-1]["selective_accuracy"] is None
