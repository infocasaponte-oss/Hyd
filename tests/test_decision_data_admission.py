# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json
from uuid import uuid4

import pytest

from hydra.model_factory.distillation import DatasetBuilder, _ok
from hydra.telemetry.metrics import TaskRecord
from hydra.training.specialists import train_text_classifier


@pytest.mark.parametrize("verified", [False, None, "true", 1])
def test_unverified_is_not_training_gold_or_negative(tmp_path, verified):
    task = TaskRecord(id=uuid4(), status="completed", request={"messages": []},
                      final_response={"answer": "answer", "meta": {"confidence": 0.99, "verified": verified}})
    assert not _ok(task, 0.1)
    assert DatasetBuilder(tmp_path).critic([task]).examples == 0


def test_no_validation_does_not_reuse_training_accuracy(tmp_path):
    source = tmp_path / "train.jsonl"
    source.write_text(json.dumps({"input": {"query": "hello"}, "output": {"label": "chat"}}))
    result = train_text_classifier(source, None, tmp_path / "model")
    assert result["train_accuracy"] == 1
    assert "valid_accuracy" not in result
    assert result["validation_status"] == "not_evaluated"
