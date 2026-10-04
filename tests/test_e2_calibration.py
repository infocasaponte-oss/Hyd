import numpy as np
import pytest

from hyd_calibrator.e2_calibration import calibration_groups, calibrate_logits


def rows(n=200):
    return [{"group_id": f"g{i}", "meta": {"person_id": f"p{i}", "family_id": f"f{i}"}} for i in range(n)]


def test_temperature_and_threshold_groups_are_disjoint_and_order_independent():
    data = rows()
    data[1] = dict(data[0])
    fit, threshold = calibration_groups(data)
    assert bool(0 in fit) == bool(1 in fit)
    assert not set(fit) & set(threshold)
    assert len(fit) + len(threshold) == len(data)
    reverse_fit, _ = calibration_groups(list(reversed(data)))
    assert {data[i]["group_id"] for i in fit} == {data[-i-1]["group_id"] for i in reverse_fit}


def test_unsatisfied_target_explicitly_abstains_all():
    data = rows()
    logits = np.tile([8.0, -8.0], (len(data), 1))
    result = calibrate_logits(logits, np.ones(len(data), dtype=int), data)
    assert result["abstain_all"] is True
    assert result["selected"] is None
    assert result["target_met"] is False


def test_supported_target_has_coverage_and_wilson_evidence():
    data = rows(1000)
    result = calibrate_logits(np.tile([8.0, -8.0], (len(data), 1)), np.zeros(len(data), dtype=int), data)
    assert result["abstain_all"] is False
    assert result["selected"]["coverage"] == 1
    assert result["selected"]["accuracy_wilson_lower_95"] >= .95
    assert result["independent_test"] is False


def test_one_group_or_inconsistent_identity_cannot_split_calibration():
    with pytest.raises(ValueError, match="independent"):
        calibration_groups([rows(1)[0]] * 10)
    data = rows()
    data[1]["meta"]["person_id"] = data[0]["meta"]["person_id"]
    with pytest.raises(ValueError, match="inconsistent"):
        calibration_groups(data)
