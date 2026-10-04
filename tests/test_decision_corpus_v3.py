# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import pytest

from hydra.training.decision_corpus_v3 import build


def test_corpus_has_frozen_disjoint_partitions_and_provenance(tmp_path):
    manifest = build(tmp_path, train_per_label=4, calibration_per_label=2, test_per_label=3)
    assert manifest["counts"] == {"train": 40, "calibration": 20, "test": 30}
    rows = {split: [json.loads(line) for line in (tmp_path / f"{split}.jsonl").read_text().splitlines()]
            for split in manifest["counts"]}
    ids = [row["id"] for values in rows.values() for row in values]
    assert len(ids) == len(set(ids))
    assert all(row["training_allowed"] is (split == "train") for split, values in rows.items() for row in values)
    assert all(row["rights"]["verified"] and row["prompt_sha256"] for values in rows.values() for row in values)
    assert not set(r["prompt_sha256"] for r in rows["train"]) & set(r["prompt_sha256"] for r in rows["test"])


def test_corpus_rejects_empty_partitions(tmp_path):
    with pytest.raises(ValueError):
        build(tmp_path, train_per_label=0)
