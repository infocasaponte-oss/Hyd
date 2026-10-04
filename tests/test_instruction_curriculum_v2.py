# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import pytest

from hydra.training.instruction_corpus_v2 import build
from hydra.router.decision_authority import DecisionAuthority
from hydra.core.contracts import DecisionObservation

# data/ is gitignored: corpus builds need the local data/hydra-corpus-v1/train.jsonl
LOCAL_DATA = __import__("pathlib").Path("data/hydra-corpus-v1/train.jsonl")
needs_local_data = pytest.mark.skipif(not LOCAL_DATA.exists(), reason=f"{LOCAL_DATA} is not in this checkout")


@needs_local_data
def test_curriculum_does_not_reuse_holdout_or_overwrite(tmp_path):
    output = tmp_path / "v2"
    manifest = build(output)
    assert manifest["files"]["train.jsonl"]["examples"] == 384
    rows = {s: [json.loads(line) for line in (output / f"{s}.jsonl").read_text(encoding="utf-8").splitlines()]
            for s in ("train", "validation", "test")}
    prompts = {s: {r["messages"][1]["content"] for r in rs} for s, rs in rows.items()}
    assert not prompts["train"] & prompts["test"]
    assert not prompts["validation"] & prompts["test"]
    with pytest.raises(FileExistsError):
        build(output)


def test_unverified_or_critical_decision_has_no_authority():
    authority = DecisionAuthority.from_evidence({"accuracy": .99}, "kev")
    assert not authority.enabled
    obs = DecisionObservation(status="observed", model="kev", selected="coding", confidence=1)
    assert authority.task_hint(obs) is None
    enabled = DecisionAuthority(True, "kev")
    assert enabled.task_hint(obs).value == "coding"
    assert enabled.task_hint(obs.model_copy(update={"selected": "tool_use"})) is None
    assert enabled.task_hint(obs.model_copy(update={"selected": "security"})) is None
