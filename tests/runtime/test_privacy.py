# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.artifacts import ArtifactStore
from hydra.runtime.privacy import PrivacyScanner, PrivacyScanStatus


def test_privacy_scanner_flags_secret_and_email(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    task_id = uuid4()
    artifact = store.put_text(
        task_id=task_id,
        kind="source",
        text="contact me@example.com\napi_key = 'supersecretvalue'\n",
    )

    result = PrivacyScanner().scan([artifact], store)

    assert result.status == PrivacyScanStatus.FLAGGED
    assert result.finding_types == ["credential_or_secret", "email"]


def test_privacy_scanner_marks_clean_complete_text_clear(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    artifact = store.put_text(
        task_id=uuid4(),
        kind="tests",
        text="all tests passed",
    )

    result = PrivacyScanner().scan([artifact], store)

    assert result.status == PrivacyScanStatus.CLEAR
    assert result.artifacts_scanned == 1


def test_privacy_scanner_is_incomplete_when_blob_exceeds_limit(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    artifact = store.put_text(
        task_id=uuid4(),
        kind="large",
        text="x" * 20,
    )

    result = PrivacyScanner(max_artifact_bytes=10).scan([artifact], store)

    assert result.status == PrivacyScanStatus.INCOMPLETE
