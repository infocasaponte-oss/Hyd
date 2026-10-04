# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

from hydra.training.create_calibrator import create


def test_create_calibrator_uses_only_calibration_rows(tmp_path):
    report = {"rows": [{"split": "calibration", "expected": "a", "probabilities": {"a": .8, "b": .2}},
                       {"split": "test", "expected": "a", "probabilities": {"a": .01, "b": .99}}],
              "dataset_manifest": {"files": {"calibration.jsonl": {"sha256": "cal"}}}}
    source = tmp_path / "report.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    result = create(source, tmp_path / "calibrator.json")
    assert result["rows"] == 1 and json.loads((tmp_path / "calibrator.json").read_text())["calibration_dataset_sha256"] == "cal"
