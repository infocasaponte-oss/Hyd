# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

from hydra.training.prepare_kev_hydra_v2 import build, CRITERIA


def test_kev_data_is_deduplicated_and_contains_full_decision_contract(tmp_path):
    manifest = build(tmp_path / "kev-data")
    rows = [json.loads(line) for line in (tmp_path / "kev-data/train.jsonl").read_text(encoding="utf-8").splitlines()]
    assert manifest["examples"] == 200 and manifest["frozen_tests_read"] is False
    assert len({r["state"] for r in rows}) == 200
    assert {r["questions"]["task"]["label"] for r in rows} == set(CRITERIA)
    assert all(set(r["questions"]["task"]["criteria"]) == set(CRITERIA) for r in rows)
