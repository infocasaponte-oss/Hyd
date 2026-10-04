# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import importlib
from uuid import uuid4

import pytest

from hydra.artifacts.blobs import LocalBlobs
from hydra.artifacts.store import ArtifactStore as PlatformStore
from hydra.artifacts.task_store import ArtifactStore
from hydra.core.eventlog import FileLog
from hydra.corpus.artifact_privacy import PrivacyScanner
from hydra.corpus.privacy_contracts import PrivacyScanStatus


@pytest.mark.parametrize("old,new", [
    ("hydra.runtime.artifacts", "hydra.artifacts.task_store"),
    ("hydra.runtime.privacy", "hydra.corpus.artifact_privacy"),
])
def test_legacy_module_is_canonical(old, new):
    assert importlib.import_module(old) is importlib.import_module(new)


def test_local_artifact_is_adopted_into_platform_blobs_without_manifest_change(tmp_path):
    root = tmp_path / "task-artifacts"
    record = ArtifactStore(root).put_text(task_id=uuid4(), kind="source", text="clean source")
    manifest = root / "manifests" / f"{record.artifact_id}.json"
    before = manifest.read_bytes()
    blobs = LocalBlobs(tmp_path / "objects")
    shared = ArtifactStore(root, blobs=blobs, log=FileLog(tmp_path / "records.jsonl", ArtifactStore.STREAM))
    assert not blobs.exists(record.sha256)
    assert shared.get_text(record.sha256) == "clean source"
    assert blobs.exists(record.sha256)
    assert PlatformStore(tmp_path / "platform", blobs=blobs).get(record.sha256) == b"clean source"
    assert manifest.read_bytes() == before
    assert shared.digest_of(record.sha256) == record.sha256


def test_shared_artifact_scan_keeps_byte_limit_and_utf8_rejection(tmp_path):
    store = ArtifactStore(tmp_path / "tasks", blobs=LocalBlobs(tmp_path / "objects"),
                          log=FileLog(tmp_path / "records.jsonl", ArtifactStore.STREAM))
    artifact = store.put_bytes(task_id=uuid4(), kind="source", data=b"\xff", media_type="text/plain")
    result = PrivacyScanner().scan([artifact], store)
    assert result.status == PrivacyScanStatus.INCOMPLETE
    assert result.artifacts_scanned == 0
    with pytest.raises(ValueError, match="read limit"):
        store.get_bytes(artifact.sha256, max_bytes=0)


def test_shared_manifests_retain_task_and_media_metadata(tmp_path):
    log = FileLog(tmp_path / "records.jsonl", ArtifactStore.STREAM)
    store = ArtifactStore(tmp_path / "tasks", blobs=LocalBlobs(tmp_path / "objects"), log=log)
    record = store.put_text(task_id=uuid4(), kind="report", text="report", metadata={"verified": False})
    _, serialized = next(iter(log.read()))
    assert type(record).model_validate_json(serialized).model_dump() == record.model_dump()
