import gzip
import json

import pytest

from hyd_calibrator.acquisition_snapshot import prepare_acquisition, file_hash


def setup_source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    rows = []
    for text, license_name in [(" Original text\n", "CC-BY-4.0"), ("original TEXT", "CC-BY-4.0"),
                               ("Requires review", "CC-BY"), ("", "CC-BY-4.0")]:
        rows.append({"text": text, "license": license_name, "source": "fixture", "source_revision": "a" * 40,
                     "language": "es", "category": "fixture", "url": "https://example.org/fixture"})
    path = root / "source.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"format": "acquisition-source-review/1", "files": [
        {"path": path.name, "sha256": file_hash(path), "bytes": path.stat().st_size}]}), encoding="utf-8")
    return root, path, inventory, rows


def test_preserves_all_originals_provenance_and_unapproved_status(tmp_path):
    root, source, inventory, rows = setup_source(tmp_path)
    before = file_hash(source)
    out = tmp_path / "snapshot"
    report = prepare_acquisition(root, inventory, out)
    assert report["counts"] == {"candidates": 1, "duplicates": 1, "review": 2}
    assert report["complete"] is True and report["training_allowed"] is False
    original = []
    for bucket in report["counts"]:
        with gzip.open(out / f"{bucket}.jsonl.gz", "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                original.append(row["original"])
                assert row["training_allowed"] is False
                assert row["provenance"]["source_file_sha256"] == before
                if bucket == "duplicates":
                    assert row["duplicate_of"]["source_line"] == 1
    assert sorted(row["text"] for row in original) == sorted(row["text"] for row in rows)
    assert file_hash(source) == before
    report2 = prepare_acquisition(root, inventory, tmp_path / "snapshot2")
    assert report2["output_sha256"] == report["output_sha256"]
    with pytest.raises(ValueError, match="already exists"):
        prepare_acquisition(root, inventory, out)


def test_modified_input_rejected_before_output(tmp_path):
    root, source, inventory, _ = setup_source(tmp_path)
    with source.open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="changed"):
        prepare_acquisition(root, inventory, tmp_path / "snapshot")
    assert not (tmp_path / "snapshot").exists()


def test_escaping_inventory_path_rejected(tmp_path):
    root, _, inventory, _ = setup_source(tmp_path)
    report = json.loads(inventory.read_text(encoding="utf-8"))
    report["files"][0]["path"] = "../elsewhere.jsonl.gz"
    inventory.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe"):
        prepare_acquisition(root, inventory, tmp_path / "snapshot")


def test_quarantined_source_does_not_hide_later_complete_candidate(tmp_path):
    root, path, inventory, rows = setup_source(tmp_path)
    rows[0]["license"] = "CC-BY"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    audit = json.loads(inventory.read_text(encoding="utf-8"))
    audit["files"][0]["sha256"] = file_hash(path)
    inventory.write_text(json.dumps(audit), encoding="utf-8")
    report = prepare_acquisition(root, inventory, tmp_path / "snapshot")
    assert report["counts"] == {"candidates": 1, "duplicates": 0, "review": 3}
    with gzip.open(tmp_path / "snapshot/candidates.jsonl.gz", "rt", encoding="utf-8") as handle:
        candidate = json.loads(next(handle))
    assert candidate["provenance"]["source_line"] == 2
