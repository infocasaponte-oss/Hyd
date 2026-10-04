"""Regression tests for consent bypasses and snapshot overwrites."""

import json

import pytest

from hyd_calibrator.admission import require_consent_and_rights
from hyd_calibrator.corpus import build, validate
from hydra.hyd.train import rows, train


@pytest.mark.parametrize("consent", [False, None, "true", 1])
@pytest.mark.parametrize("split", ["train", "calibration"])
def test_native_loader_rejects_non_literal_consent(tmp_path, consent, split):
    row = {"consent": consent, "rights": {"verified": True, "license": "proprietary-hydra-authored"},
           "split": split, "training_allowed": split == "train",
           "input": {"query": "  audit question  "}, "output": {"task_type": "chat"}}
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="consent"):
        rows(path, training=split == "train")


def test_source_requires_explicit_template_flag_and_rights(tmp_path):
    row = {"text": " question ", "expected": "chat", "meta": {"consent": True, "real": True}}
    path = tmp_path / "source.jsonl"
    path.write_text(json.dumps(row) + "\n")
    assert validate(path)[1]["valid_rows"] == 0
    row["meta"]["suspect_template"] = False
    path.write_text(json.dumps(row) + "\n")
    assert validate(path)[1]["valid_rows"] == 0
    with pytest.raises(ValueError, match="rights"):
        require_consent_and_rights({"consent": True})


def test_existing_outputs_are_immutable(tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    marker = out / "model.json"
    marker.write_bytes(b"original")
    with pytest.raises(ValueError, match="already exists"):
        train(tmp_path / "missing", tmp_path / "missing", out)
    with pytest.raises(ValueError, match="already exists"):
        build(tmp_path / "missing", out)
    assert marker.read_bytes() == b"original"
