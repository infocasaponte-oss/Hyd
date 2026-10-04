# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

from hydra.training import grounded_corpus_v1 as v1
from hydra.training import grounded_corpus_v2 as v2
from hydra.training import grounded_corpus_v3 as v3
from hydra.training.program import validate_corpus


def test_eight_training_wordings_and_held_out_ones_unchanged():
    assert len(v3.WORDING["train"]) == 8
    for family, questions in v3.QUESTIONS.items():
        assert questions[:5] == v2.QUESTIONS[family]  # validation/calibration/test wordings are v2's
        assert len(set(questions)) == len(questions)
    held_out = {i for split in ("validation", "calibration", "test") for i in v3.WORDING[split]}
    assert not held_out & set(v3.WORDING["train"])


def test_rules_and_repeal_polarity_are_kept():
    assert all(q.endswith(v2.FUNCTION_RULE) for q in v3.QUESTIONS["code_functions"])
    assert all(q.endswith(v2.IMPORT_RULE) for q in v3.QUESTIONS["code_imports"])
    # every repeal wording asks whether it IS repealed, so "Sí./No." keeps its meaning
    assert all("derog" in q.lower() and "vigente" not in q.lower() for q in v3.QUESTIONS["boe_repealed"])


def test_build_uses_all_training_wordings_and_v1_splits(tmp_path):
    from tests.test_grounded_corpus_v1 import boe_record
    from tests.test_grounded_corpus_v2 import TRAPS, record

    boe = tmp_path / "boe.jsonl"
    boe.write_text("".join(json.dumps(boe_record(f"BOE-A-2099-{i}"), ensure_ascii=False) + "\n" for i in range(120)),
                   encoding="utf-8")
    code = tmp_path / "code.jsonl"
    code.write_text("".join(json.dumps(record(f"t{i}", f"# {i}\n" + TRAPS)) + "\n" for i in range(60)), encoding="utf-8")
    manifest = v3.build(tmp_path / "out", boe, code, quotas=dict.fromkeys(v3.QUESTIONS, 12))
    validate_corpus(tmp_path / "out")
    assert manifest["version"] == "grounded-v3"
    used = set()
    for split in v1.SPLITS:
        for line in (tmp_path / "out" / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            index = int(row["wording_family"].rsplit("-", 1)[1])
            assert index in v3.WORDING[split] and v1.split_for(row["provenance"]["document_id"]) == split
            if split == "train":
                used.add(index)
    assert len(used) > 2  # more than v2's two training wordings actually appear
