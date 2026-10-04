import json

import pytest

from hyd_calibrator.contract import CRITERIA
from hyd_calibrator.e2_admission import admit_dataset


def dataset(path, change=None):
    for split in ("train", "calibration", "test"):
        rows = []
        for label in CRITERIA:
            row = {"split": split, "training_allowed": split == "train", "consent": True,
                   "rights": {"verified": True, "license": "owner-declared"},
                   "input": {"query": f"{split} {label}"}, "output": {"task_type": label},
                   "group_id": f"group-{split}", "meta": {"real": True, "suspect_template": False,
                   "person_id": f"person-{split}", "family_id": f"family-{split}-{label}"}}
            if change and split == "test":
                change(row)
            rows.append(row)
        (path / f"{split}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_admitted_partition_hashes_and_verbatim_text(tmp_path):
    dataset(tmp_path)
    rows, hashes = admit_dataset(tmp_path, "a" * 40)
    assert rows["train"][0]["input"]["query"].startswith("train ")
    assert set(hashes) == {"train", "calibration", "test"}
    assert len(set(hashes.values())) == 3
    assert admit_dataset(tmp_path, "a" * 40)[1] == hashes


@pytest.mark.parametrize("change", [
    lambda row: row.update(consent=False),
    lambda row: row.update(training_allowed=True),
    lambda row: row["rights"].update(verified=False),
    lambda row: row["meta"].update(person_id="person-train"),
    lambda row: row["meta"].update(family_id="family-train-chat"),
    lambda row: row.update(group_id="group-train"),
    lambda row: row["input"].update(query="train chat"),
    lambda row: row["meta"].pop("person_id"),
])
def test_invalid_permissions_missing_provenance_and_leakage_rejected(tmp_path, change):
    dataset(tmp_path, change)
    with pytest.raises(ValueError):
        admit_dataset(tmp_path, "a" * 40)


def test_mutable_encoder_and_missing_class_rejected(tmp_path):
    dataset(tmp_path)
    with pytest.raises(ValueError, match="immutable"):
        admit_dataset(tmp_path, "main")
    path = tmp_path / "test.jsonl"
    path.write_text("\n".join(path.read_text(encoding="utf-8").splitlines()[1:]), encoding="utf-8")
    with pytest.raises(ValueError, match="ten classes"):
        admit_dataset(tmp_path, "a" * 40)
