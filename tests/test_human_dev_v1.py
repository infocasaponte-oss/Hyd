# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

from hydra.training.human_dev_v1 import build


def test_human_dev_is_separate_and_trainable(tmp_path):
    manifest = build(tmp_path / "dev.jsonl")
    rows = [json.loads(line) for line in (tmp_path / "dev.jsonl").read_text().splitlines()]
    assert manifest["examples"] == 100 and all(row["training_allowed"] for row in rows)
