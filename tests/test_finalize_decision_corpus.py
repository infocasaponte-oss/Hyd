# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

from hydra.training.finalize_decision_corpus import finalize


def test_finalize_ignores_unknown_labels_and_does_not_reinfer(tmp_path):
    report = {"rows": [
        {"split": "calibration", "expected": "a", "probabilities": {"a": .9, "b": .1}, "selected": "a"},
        {"split": "test", "expected": "unknown", "probabilities": {"a": .9, "b": .1}, "selected": "a"},
    ], "dataset_manifest": {"files": {"calibration.jsonl": {"sha256": "x"}}}}
    source = tmp_path / "partial.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    result = finalize(source, tmp_path / "result.json")
    assert result["status"] == "EVALUATED" and result["test_raw"]["valid"] == 0
