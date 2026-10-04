# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import pytest

from hydra.training.create_local_calibration import create
from hydra.training.specialists import TextClassifier


@pytest.mark.parametrize("split,admitted", [("test", False), ("train", True), ("calibration", True)])
def test_training_and_test_rows_cannot_fit_calibration(tmp_path, split, admitted):
    model = tmp_path / "model.json"
    TextClassifier(["chat", "coding"], dims=8).save(model)
    dataset = tmp_path / "rows.jsonl"
    dataset.write_text(json.dumps({"split": split, "training_allowed": admitted,
                                   "input": {"query": "hola"}, "output": {"task_type": "chat"}}))
    output = tmp_path / "calibration.json"
    with pytest.raises(ValueError, match="reserved calibration"):
        create(model, dataset, output)
    assert not output.exists()
