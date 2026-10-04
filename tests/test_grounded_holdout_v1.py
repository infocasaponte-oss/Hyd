# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import pytest

from hydra.training import grounded_corpus_v3 as v3
from hydra.training import grounded_holdout_v1 as h


def test_holdout_wordings_are_new():
    seen = {q for questions in v3.QUESTIONS.values() for q in questions}
    assert set(h.HOLDOUT_WORDINGS) == set(v3.QUESTIONS)
    assert not seen & set(h.HOLDOUT_WORDINGS.values())


def test_holdout_excludes_used_documents_and_is_sealed(tmp_path):
    from tests.test_grounded_corpus_v1 import boe_record

    rows = []
    for i in range(60):
        record = boe_record(f"BOE-A-2099-{i}")
        record["metadata"]["estatus_derogacion"] = "S" if i % 5 == 0 else "N"
        rows.append(json.dumps(record, ensure_ascii=False))
    boe = tmp_path / "boe.jsonl"
    boe.write_text("\n".join(rows) + "\n", encoding="utf-8")
    code = tmp_path / "code.jsonl"
    code.write_text("", encoding="utf-8")
    used = tmp_path / "used-corpus"
    used.mkdir()
    (used / "train.jsonl").write_text(json.dumps({"provenance": {"document_id": "BOE-A-2099-1"}}) + "\n", encoding="utf-8")
    snapshot = tmp_path / "snap.jsonl"
    snapshot.write_text(json.dumps({"document_id": "BOE-A-2099-2"}) + "\n", encoding="utf-8")
    manifest = h.build(tmp_path / "out", boe, code, [used], [snapshot])
    ids = {json.loads(line)["provenance"]["document_id"]
           for line in (tmp_path / "out" / "holdout.jsonl").read_text(encoding="utf-8").splitlines()}
    assert ids and "BOE-A-2099-1" not in ids and "BOE-A-2099-2" not in ids
    assert manifest["sealed"] and manifest["repeal_balance"]["si"] >= 1
    with pytest.raises(FileExistsError):
        h.build(tmp_path / "out", boe, code, [used], [snapshot])
