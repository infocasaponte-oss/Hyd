# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.artifacts import ArtifactStore


def test_artifact_store_is_content_addressed(tmp_path):
    store = ArtifactStore(tmp_path)
    task_id = uuid4()
    a = store.put_text(task_id=task_id, kind="test-output", text="same")
    b = store.put_text(task_id=task_id, kind="test-output", text="same")
    assert a.sha256 == b.sha256
    blobs = list((tmp_path / "sha256").rglob(a.sha256))
    assert len(blobs) == 1
