# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import gzip
import json

import pytest

from hyd_calibrator.data_review import acquisition_report, deduplicate_evaluation


def test_dedup_preserves_original_and_reference_without_certifying(tmp_path):
    rows = [{"prompt": "  Original question\n", "expected_response": "answer", "id": 1},
            {"prompt": "original   QUESTION", "expected_response": "answer", "id": 2}]
    source = tmp_path / "input.json"
    source.write_text(json.dumps(rows), encoding="utf-8")
    out = tmp_path / "review"
    report = deduplicate_evaluation(source, out, text_field="prompt", reference_field="expected_response",
                                   evaluation_kind="general-response")
    assert report["rows"] == 2 and report["unique"] == 1
    assert report["evaluation_kind"] == "general-response"
    assert report["training_allowed"] is False and report["accuracy_measured"] is False
    assert json.loads((out / "original.json").read_text(encoding="utf-8")) == rows
    assert json.loads((out / "deduplicated.json").read_text(encoding="utf-8")) == rows[:1]
    with pytest.raises(ValueError, match="already exists"):
        deduplicate_evaluation(source, out, text_field="prompt", reference_field="expected_response", evaluation_kind="general-response")


def test_conflicting_duplicate_labels_require_review(tmp_path):
    source = tmp_path / "input.jsonl"
    source.write_text('\n'.join(json.dumps(row) for row in [{"text": "Same", "expected": "chat"},
                                                             {"text": "same", "expected": "research"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="conflicting"):
        deduplicate_evaluation(source, tmp_path / "out", text_field="text", reference_field="expected", evaluation_kind="hyd-routing")
    assert not (tmp_path / "out").exists()
    report = deduplicate_evaluation(source, tmp_path / "inspection", text_field="text", reference_field="expected",
                                   evaluation_kind="hyd-routing", review_only=True)
    assert report["conflicting_reference_groups"] == [[0, 1]]
    assert report["deduplicated_ready"] is False
    assert not (tmp_path / "inspection" / "deduplicated.json").exists()


def test_acquisition_counts_sources_and_duplicates_without_inventing_tokens(tmp_path):
    source = tmp_path / "sample.jsonl.gz"
    with gzip.open(source, "wt", encoding="utf-8") as handle:
        for text in ("Original", " original ", ""):
            handle.write(json.dumps({"text": text, "source": "fixture", "license": "CC-BY", "language": "es", "category": "modern"}) + '\n')
    report = acquisition_report(tmp_path, tmp_path / "report.json")
    group = report["groups"][0]
    assert group["rows"] == 3 and group["empty"] == 1 and group["normalized_duplicates"] == 1
    assert report["tokens_measured"] is False and report["training_admission"] is False
    assert report["files"][0]["sha256"]
