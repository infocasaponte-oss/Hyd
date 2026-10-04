# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from copy import deepcopy

import pytest

from hydra.training.compare_evaluations import compare


def report():
    return {"status": "EVALUATED", "subset": False, "dataset_sha256": "dataset",
            "model_identity": {"digest": "manifest", "artifact_sha256": "weights"},
            "cases": [{"id": "a", "passed": True}, {"id": "b", "passed": False}]}


def test_comparison_recomputes_score_and_reports_regressions():
    base = report()
    candidate = deepcopy(base)
    candidate["score"] = 1.0
    candidate["cases"][0]["passed"] = False
    result = compare(base, candidate)
    assert result["candidate_score"] == 0
    assert result["score_delta"] == -0.5
    assert result["regressions"] == ["a"]
    assert result["approved"] is False


@pytest.mark.parametrize("field,value", [("status", "EVALUATING"), ("subset", True),
                                        ("dataset_sha256", "different"), ("model_identity", {})])
def test_reject_incomparable_reports(field, value):
    candidate = report()
    candidate[field] = value
    with pytest.raises(ValueError):
        compare(report(), candidate)
