# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import pytest

from hydra.training.decision_benchmark import cases, questions
from hydra.training.decision_metrics import metrics, select_threshold, wilson_lower


def row(prob=0.9, correct=True):
    return {"expected": "a", "selected": "a" if correct else "b",
            "probabilities": {"a": prob if correct else 1-prob, "b": 1-prob if correct else prob}}


def test_exact_scores_and_no_missing_results_denominator_shrink():
    result = metrics([row(), {"expected": "a", "error": "Timeout"}])
    assert result["coverage"] == 0.5 and result["accuracy"] == 1
    assert result["ece_10_bins"] == pytest.approx(0.1)
    assert result["brier_multiclass_sum"] == pytest.approx(0.02)
    assert wilson_lower(0, 0) == 0
    assert wilson_lower(24, 24) < 0.9


def test_overconfident_errors_and_abstain_all_are_not_perfect():
    result = metrics([row(correct=False)], threshold=1.01)
    assert result["accuracy"] is None and result["coverage"] == 0
    assert result["ece_10_bins"] == pytest.approx(0.9)
    assert select_threshold([row(correct=False)] * 24) == 1.01


def test_select_threshold_on_calibration_without_test_access():
    calibration = [row(0.95)] * 12 + [row(0.6, correct=False)] * 12
    assert select_threshold(calibration) == 0.7
    assert metrics([row(0.99, correct=False)], 0.7)["accuracy"] == 0


def test_splits_and_option_order_preserve_labels():
    rows = cases()
    assert len({r["text"] for r in rows}) == len(rows)
    assert sum(r["split"] == "test" for r in rows) == 24
    assert sum(r["split"] == "calibration" for r in rows) == 24
    assert len([r for r in rows if r["split"] == "test" and r["id"].endswith("-4")]) == 6
    assert questions()["task"]["criteria"] == questions(True)["task"]["criteria"]
    assert list(questions()["task"]["criteria"]) == list(reversed(questions(True)["task"]["criteria"]))
