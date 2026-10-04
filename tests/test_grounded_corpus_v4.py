# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

from hydra.training import grounded_corpus_v1 as v1
from hydra.training import grounded_corpus_v3 as v3
from hydra.training import grounded_corpus_v4 as v4
from hydra.training.program import validate_corpus


def test_repeal_family_is_balanced_and_everything_else_is_v3(tmp_path):
    from tests.test_grounded_corpus_v1 import boe_record

    rows = []
    for i in range(200):
        record = boe_record(f"BOE-A-2099-{i}")
        record["metadata"]["estatus_derogacion"] = "S" if i % 10 == 0 else "N"  # 10 % repealed, as in the BOE
        rows.append(json.dumps(record, ensure_ascii=False))
    boe = tmp_path / "boe.jsonl"
    boe.write_text("\n".join(rows) + "\n", encoding="utf-8")
    code = tmp_path / "code.jsonl"
    code.write_text("", encoding="utf-8")
    quotas = dict.fromkeys(v4.QUESTIONS, 1) | {"boe_repealed": 20}
    manifest = v4.build(tmp_path / "out", boe, code, quotas=quotas)
    validate_corpus(tmp_path / "out")
    assert manifest["version"] == "grounded-v4"
    assert manifest["repeal_balance"] == {"si": 8, "no": 12}
    assert v4.QUESTIONS is v3.QUESTIONS and v4.WORDING is v3.WORDING
    for split in v1.SPLITS:
        for line in (tmp_path / "out" / f"{split}.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            assert v1.split_for(row["provenance"]["document_id"]) == split
