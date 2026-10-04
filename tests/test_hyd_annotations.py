import hashlib
import json

import pytest

from hyd_calibrator.annotations import validate_annotation, validate_annotations
from hyd_calibrator.contract import CRITERIA
from hyd_calibrator.corpus import build


def event(text, **changes):
    result = {"format": "hyd-human-annotation/1", "event_id": "e1", "reviewer_id": "person-1",
              "reviewer_kind": "human", "created_at": "2026-10-04T19:00:00+00:00",
              "record_sha256": hashlib.sha256(text.encode()).hexdigest(), "status": "pending",
              "risk_kind": "unknown", "context_status": "unknown", "abstain_reason": "unknown"}
    return dict(result, **changes)


def test_pending_is_not_a_negative_and_text_is_bound():
    text = "  original question\n"
    original = event(text)
    assert validate_annotation(original, text) == original
    with pytest.raises(ValueError, match="hash"):
        validate_annotation(original, text.strip())
    with pytest.raises(ValueError, match="pending"):
        validate_annotation(event(text, risk_kind="benign"), text)


@pytest.mark.parametrize("changes", [
    {"reviewer_kind": "ai"}, {"created_at": "2026-10-04T19:00:00"},
    {"status": "reviewed"}, {"risk_kind": []},
    {"status": "reviewed", "abstain_reason": "dangerous", "risk_kind": "benign"},
    {"status": "reviewed", "abstain_reason": "missing_context", "context_status": "sufficient"},
])
def test_invalid_or_inferred_annotations_are_rejected(changes):
    with pytest.raises(ValueError):
        validate_annotation(event("question", **changes), "question")


def test_history_cannot_duplicate_or_overwrite_events():
    first = event("question")
    second = event("question", event_id="e2", status="reviewed", risk_kind="dangerous",
                   abstain_reason="dangerous")
    assert validate_annotations([first, second], "question") == [first, second]
    with pytest.raises(ValueError, match="duplicate"):
        validate_annotations([first, first], "question")


def test_builder_preserves_annotation_history_original_label_and_text(tmp_path):
    source = tmp_path / "source.jsonl"
    records = []
    for label in CRITERIA:
        text = f"  original {label}\n"
        records.append({"text": text, "expected": label,
                        "meta": {"consent": True, "real": True, "suspect_template": False},
                        "rights": {"verified": True, "license": "owner-declaration"},
                        "annotations": [event(text)]})
    source.write_text("".join(json.dumps(row) + "\n" for row in records))
    out = tmp_path / "snapshot"
    build(source, out)
    derived = [json.loads(line) for name in ("train", "calibration", "test")
               for line in (out / f"{name}.jsonl").read_text().splitlines()]
    by_label = {row["output"]["task_type"]: row for row in derived}
    for row in records:
        copy = by_label[row["expected"]]
        assert copy["input"]["query"] == row["text"]
        assert copy["annotations"] == row["annotations"]
        assert copy["rights"] == row["rights"]
