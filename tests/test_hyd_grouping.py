# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json

import pytest

from hyd_calibrator.grouping import grouped_partitions
from hyd_calibrator.corpus import build
from hyd_calibrator.contract import CRITERIA


def records():
    return [{"text": f"original question {i}", "expected": list(CRITERIA)[i % len(CRITERIA)],
             "rights": {"verified": True, "license": "owner-declared"},
             "meta": {"consent": True, "real": True, "suspect_template": False,
                      "person_id": f"p{i}", "family_id": f"f{i}"}} for i in range(200)]


def test_transitive_links_and_order_invariance():
    rows = records()
    rows[1]["meta"]["person_id"] = rows[0]["meta"]["person_id"]
    rows[2]["meta"]["family_id"] = rows[1]["meta"]["family_id"]
    assignments = grouped_partitions(rows)
    assert assignments[0] == assignments[1] == assignments[2]
    assert grouped_partitions(list(reversed(rows))) == list(reversed(assignments))
    for field in ("person_id", "family_id"):
        locations = {}
        for row, (split, _) in zip(rows, assignments):
            locations.setdefault(row["meta"][field], set()).add(split)
        assert all(len(value) == 1 for value in locations.values())


def test_missing_provenance_and_one_person_fail_before_output(tmp_path):
    rows = records()
    for row in rows:
        row["meta"]["person_id"] = "one-person-many-accounts"
    source = tmp_path / "source.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="independent groups"):
        build(source, tmp_path / "snapshot", grouped=True)
    assert not (tmp_path / "snapshot").exists()
    rows[0]["meta"].pop("person_id")
    with pytest.raises(ValueError, match="person_id"):
        grouped_partitions(rows)


def test_snapshot_preserves_inputs_and_disjoint_components(tmp_path):
    rows = records()
    source = tmp_path / "source.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    report = build(source, tmp_path / "snapshot", grouped=True)
    assert report["independence_verified"] is False
    groups = []
    restored = []
    for split in ("train", "calibration", "test"):
        part = [json.loads(line) for line in (tmp_path / "snapshot" / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()]
        groups.append({row["group_id"] for row in part})
        restored.extend(row["input"]["query"] for row in part)
    assert not groups[0] & groups[1] and not groups[0] & groups[2] and not groups[1] & groups[2]
    assert sorted(restored) == sorted(row["text"] for row in rows)


def test_four_partition_mode_is_disjoint():
    data = records()
    assignments = grouped_partitions(data, development=True)
    assert {split for split, _ in assignments} == {"train", "development", "calibration", "test"}
    assert grouped_partitions(list(reversed(data)), development=True) == list(reversed(assignments))
