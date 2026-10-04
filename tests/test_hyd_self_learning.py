# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import pytest

from hydra.hyd.corpus import build, SPLITS
from hydra.hyd.model import CandidateRanker
from hydra.hyd.self_learning import prepare, verified_source
from hydra.training.base_corpus import file_sha256


def test_verified_error_replay_is_bounded_and_keeps_evaluation_fixed(tmp_path):
    source = tmp_path / "source"
    build(source, per_domain=12)
    model = tmp_path / "model.json"
    CandidateRanker().save(model)
    out = tmp_path / "round"
    before = file_sha256(model)
    report = prepare(source, model, out, max_error_copies=1000)
    assert report["observed_errors"] > 0
    assert 0 < report["extra_error_copies"] <= report["training_examples"] // 2
    assert not report["training_started"] and not report["authority_enabled"]
    assert report["privacy_quarantined_training_records"] > 0
    assert before == file_sha256(model)
    for split in SPLITS[1:]:
        assert (source / (split + ".jsonl")).read_bytes() == (out / (split + ".jsonl")).read_bytes()
    rows = [json.loads(line) for line in (out / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(row["split"] == "train" and row["training_allowed"] for row in rows)
    with pytest.raises(FileExistsError):
        prepare(source, model, out)


def test_claimed_verified_labels_with_updated_checksum_are_rejected(tmp_path):
    source = tmp_path / "source"
    build(source, per_domain=12)
    path = source / "train.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    keys = list(rows[0]["target"])
    target = max(rows[0]["target"], key=rows[0]["target"].get)
    wrong = next(key for key in keys if key != target)
    rows[0]["target"] = {key: float(key == wrong) for key in keys}
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["files"][path.name]["sha256"] = file_sha256(path)
    (source / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="reproduce"):
        verified_source(source)
