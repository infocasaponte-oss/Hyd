# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.training.human_dev_v1 import build
from hydra.training.train_decision_v2 import train


def test_human_development_is_accepted_by_training(tmp_path):
    dev = tmp_path / "dev.jsonl"
    build(dev)
    result = train(output=tmp_path / "model", human_dev=dev)
    assert str(dev) in result["manifest"]["training_corpus"]
