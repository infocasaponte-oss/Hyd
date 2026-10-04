import json

import pytest

from hyd_calibrator.corpus_trash import finish, plan_duplicates, stage


def corpus(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "a.jsonl.gz").write_bytes(b"identical fixture bytes")
    (root / "b.jsonl.gz").write_bytes(b"identical fixture bytes")
    (root / "c.jsonl.gz").write_bytes(b"unique fixture")
    (root / "_tmp").mkdir()
    (root / "_tmp" / "active.jsonl.gz").write_bytes(b"identical fixture bytes")
    plan = tmp_path / "plan.json"
    report = plan_duplicates(root, plan)
    assert report["scanned_files"] == 3 and len(report["entries"]) == 1
    return root, plan


def test_restore_and_empty_preserve_kept_bytes_and_audit(tmp_path):
    root, plan = corpus(tmp_path)
    batch = stage(root, plan)["batch"]
    assert not (root / "b.jsonl.gz").exists()
    finish(root, batch)
    assert (root / "b.jsonl.gz").read_bytes() == (root / "a.jsonl.gz").read_bytes()
    batch = stage(root, plan)["batch"]
    result = finish(root, batch, purge=True)
    assert result["state"] == "purged"
    assert (root / ".trash" / batch / "manifest.json").is_file()
    assert (root / "a.jsonl.gz").is_file() and (root / "_tmp" / "active.jsonl.gz").is_file()
    assert finish(root, batch, purge=True)["state"] == "purged"


def test_empty_refuses_when_retained_copy_changes(tmp_path):
    root, plan = corpus(tmp_path)
    batch = stage(root, plan)["batch"]
    (root / "a.jsonl.gz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="retained"):
        finish(root, batch, purge=True)
    assert (root / ".trash" / batch / "0").exists()
    finish(root, batch)
    assert (root / "b.jsonl.gz").read_bytes() == b"identical fixture bytes"


def test_restore_refuses_overwrite(tmp_path):
    root, plan = corpus(tmp_path)
    batch = stage(root, plan)["batch"]
    (root / "b.jsonl.gz").write_bytes(b"new source")
    with pytest.raises(ValueError, match="overwrite"):
        finish(root, batch)
    assert (root / "b.jsonl.gz").read_bytes() == b"new source"


@pytest.mark.parametrize("path", ["../outside.jsonl.gz", "_tmp/active.jsonl.gz", "file.part"])
def test_unsafe_and_active_paths_rejected(tmp_path, path):
    root, plan = corpus(tmp_path)
    data = json.loads(plan.read_text())
    data["entries"][0]["path"] = path
    plan.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        stage(root, plan)
    assert (root / "b.jsonl.gz").exists()


def test_modified_plan_and_missing_backup_fail_before_moves(tmp_path):
    root, plan = corpus(tmp_path)
    (root / "a.jsonl.gz").unlink()
    with pytest.raises(ValueError, match="retained"):
        stage(root, plan)
    assert (root / "b.jsonl.gz").exists()


def test_exclusive_operation_lock(tmp_path):
    root, plan = corpus(tmp_path)
    (root / ".trash").mkdir()
    (root / ".trash" / "operation.lock").write_text("busy")
    with pytest.raises(FileExistsError):
        stage(root, plan)
    assert (root / "b.jsonl.gz").exists()
