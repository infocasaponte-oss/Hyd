# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import hashlib
import json
import stat
import zipfile

import pytest

from hyd_calibrator.export_bundle import verify_bundle


def bundle(tmp_path, payload=b'{"text":"private fixture"}\n', manifest=None, extra=None):
    source = tmp_path / "export.zip"
    if manifest is None:
        manifest = {"files": [{"path": "private/records.jsonl", "sha256": hashlib.sha256(payload).hexdigest()}]}
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("MANIFEST.json", json.dumps(manifest))
        z.writestr("private/records.jsonl", payload)
        if extra:
            z.writestr(*extra)
    return source


def test_verified_integrity_never_approves_training_or_human_truth(tmp_path):
    source = bundle(tmp_path)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    report = verify_bundle(source, digest)
    assert report["verified_files"] == 1
    assert report["archive_hash_bound"]
    assert not report["training_approved"]
    assert not report["human_annotations_confirmed"]
    assert "private fixture" not in json.dumps(report)
    assert not (tmp_path / "private").exists()


def test_wrong_archive_hash(tmp_path):
    with pytest.raises(ValueError, match="archive SHA"):
        verify_bundle(bundle(tmp_path), "0" * 64)


def test_changed_payload(tmp_path):
    source = bundle(tmp_path, manifest={"files": {"private/records.jsonl": "0" * 64}})
    with pytest.raises(ValueError, match="file SHA"):
        verify_bundle(source)


@pytest.mark.parametrize("path", ["../outside", "/absolute", "C:/escape", "private/./escape"])
def test_unsafe_paths(tmp_path, path):
    with pytest.raises(ValueError, match="unsafe"):
        verify_bundle(bundle(tmp_path, extra=(path, b"data")))


def test_backslash_manifest_path(tmp_path):
    source = bundle(tmp_path, manifest={"files": {"private\\records.jsonl": "0" * 64}})
    with pytest.raises(ValueError, match="unsafe"):
        verify_bundle(source)


def test_unlisted_payload(tmp_path):
    with pytest.raises(ValueError, match="cover"):
        verify_bundle(bundle(tmp_path, extra=("unlisted.jsonl", b"hidden")))


def test_duplicate_zip_entry(tmp_path):
    with pytest.warns(UserWarning):
        source = bundle(tmp_path, extra=("private/records.jsonl", b"replacement"))
    with pytest.raises(ValueError, match="duplicate"):
        verify_bundle(source)


def test_symlink_and_budget(tmp_path):
    entry = zipfile.ZipInfo("link")
    entry.create_system = 3
    entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    source = bundle(tmp_path, extra=(entry, b"target"))
    with pytest.raises(ValueError, match="symlink"):
        verify_bundle(source)
    with pytest.raises(ValueError, match="budget"):
        verify_bundle(source, max_bytes=1)


def test_missing_file_and_duplicate_manifest_key(tmp_path):
    source = bundle(tmp_path, manifest={"files": {"missing": "0" * 64}})
    with pytest.raises(ValueError, match="cover"):
        verify_bundle(source)
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("MANIFEST.json", '{"files":{},"files":{}}')
    with pytest.raises(ValueError, match="duplicate JSON"):
        verify_bundle(source)
