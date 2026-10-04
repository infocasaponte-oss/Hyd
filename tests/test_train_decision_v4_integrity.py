# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import json

import pytest

from hydra.training.train_decision_v4 import train


def test_training_deduplicates_and_preserves_reviewed_source(tmp_path):
    source = tmp_path / "reviewed.jsonl"
    rows = [{"text": "Hola mundo", "expected": "chat", "training_allowed": True},
            {"text": " hola  MUNDO ", "expected": "chat", "training_allowed": True},
            {"text": "Escribe código", "expected": "coding", "training_allowed": True}]
    source.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    before = source.read_bytes()
    report = train([source], tmp_path / "classifier.json", epochs=1)
    assert source.read_bytes() == before
    assert report["examples"] == 2 and report["duplicates_removed"] == 1
    assert report["source_sha256"][str(source)] == hashlib.sha256(before).hexdigest()


def test_conflicting_labels_do_not_write_model(tmp_path):
    source = tmp_path / "conflict.jsonl"
    source.write_text("\n".join(json.dumps({"text": "same", "expected": label,
                                            "training_allowed": True}) for label in ["chat", "coding"]))
    model = tmp_path / "classifier.json"
    with pytest.raises(ValueError, match="conflicting labels"):
        train([source], model)
    assert not model.exists()
