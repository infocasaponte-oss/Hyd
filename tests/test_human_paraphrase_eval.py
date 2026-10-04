# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

from hydra.training.human_paraphrase_eval import build


def test_human_set_is_independent_and_not_trainable(tmp_path):
    manifest = build(tmp_path / "human.jsonl")
    rows = [json.loads(line) for line in (tmp_path / "human.jsonl").read_text().splitlines()]
    assert manifest["examples"] == 100 and len({row["text"] for row in rows}) == 100
    assert all(row["training_allowed"] is False for row in rows)
