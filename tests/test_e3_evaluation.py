# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib

import pytest

from hyd_calibrator.e3_evaluation import evaluate_e3


def fixture():
    rows, predictions, selections = [], {}, {}
    for index, (risk, context, pred_risk, pred_context) in enumerate([
        ("dangerous", "missing", True, False), ("benign", "sufficient", True, False),
        ("unknown", "missing", False, True), ("privacy", "unknown", False, True),
    ]):
        text = f"fixture {index}"
        key = hashlib.sha256(text.encode()).hexdigest()
        event = {"format": "hyd-human-annotation/1", "event_id": f"event-{index}",
                 "record_sha256": key, "reviewer_id": "declared-reviewer", "reviewer_kind": "human",
                 "created_at": "2026-10-04T00:00:00Z", "status": "reviewed", "risk_kind": risk,
                 "context_status": context, "abstain_reason": "unknown"}
        rows.append({"text": text, "annotations": [event]})
        predictions[key] = {"dangerous": pred_risk, "missing_context": pred_context}
        selections[key] = event["event_id"]
    return rows, predictions, selections


def test_unknowns_not_negatives_and_type_metrics():
    report = evaluate_e3(*fixture())
    risk = report["overall"]["dangerous"]
    assert risk["tp"] == 1 and risk["fp"] == 1 and risk["unknown"] == 2
    assert risk["precision"] == .5 and risk["false_positive_rate"] == 1
    assert report["overall"]["missing_context"]["recall"] == .5
    assert report["authority"] is False


def test_no_implicit_latest_review_or_invented_zero_metric():
    rows, predictions, _ = fixture()
    report = evaluate_e3(rows, predictions, {})
    assert report["excluded"]["unselected"] == 4
    assert report["overall"]["dangerous"]["precision"] is None


def test_ai_and_missing_event_or_prediction_rejected():
    rows, predictions, selections = fixture()
    key = next(iter(selections))
    with pytest.raises(ValueError, match="not found"):
        evaluate_e3(rows, predictions, {key: "not-an-event"})
    with pytest.raises(ValueError, match="prediction"):
        evaluate_e3(rows, {}, selections)
    rows[0]["annotations"][0]["reviewer_kind"] = "ai"
    with pytest.raises(ValueError):
        evaluate_e3(rows, predictions, selections)
