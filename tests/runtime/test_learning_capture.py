# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.artifacts import ArtifactStore
from hydra.runtime.beliefs import BeliefStatus, BeliefStore
from hydra.runtime.corpus import (
    CorpusStatus,
    CorpusStore,
    QualityTier,
    RightsDeclaration,
)
from hydra.runtime.learning_capture import LearningCapture
from hydra.runtime.privacy import PrivacyScanStatus


def test_verified_experience_is_quarantined_by_default(tmp_path):
    task_id = uuid4()
    artifacts = ArtifactStore(tmp_path / "artifacts")
    artifact = artifacts.put_text(task_id=task_id, kind="tests-after", text="1 passed")
    capture = LearningCapture(
        beliefs=BeliefStore(tmp_path / "beliefs.jsonl"),
        corpus=CorpusStore(tmp_path / "corpus.jsonl"),
        artifacts_store=artifacts,
    )
    belief, record = capture.capture_verified_patch(task_id=task_id, artifacts=[artifact])
    assert belief.status == BeliefStatus.VERIFIED
    assert record.status == CorpusStatus.QUARANTINED
    assert record.privacy_scan.status == PrivacyScanStatus.CLEAR
    assert record.quality_tier == QualityTier.BRONZE


def test_training_requires_all_rights_and_clear_privacy(tmp_path):
    task_id = uuid4()
    artifacts = ArtifactStore(tmp_path / "artifacts")
    artifact = artifacts.put_text(
        task_id=task_id,
        kind="patch",
        text="diff",
    )
    capture = LearningCapture(
        beliefs=BeliefStore(tmp_path / "beliefs.jsonl"),
        corpus=CorpusStore(tmp_path / "corpus.jsonl"),
        artifacts_store=artifacts,
    )
    _, record = capture.capture_verified_patch(
        task_id=task_id,
        artifacts=[artifact],
        rights=RightsDeclaration(
            rights_confirmed=True,
            privacy_reviewed=True,
            training_allowed=True,
            source_license="internal-approved",
        ),
    )
    assert record.status == CorpusStatus.CURATED
    assert record.privacy_scan.status == PrivacyScanStatus.CLEAR
    assert len(record.content_hash) == 64


def test_flagged_privacy_blocks_training_even_with_rights(tmp_path):
    task_id = uuid4()
    artifacts = ArtifactStore(tmp_path / "artifacts")
    artifact = artifacts.put_text(
        task_id=task_id,
        kind="source",
        text="api_key = 'supersecretvalue'",
    )
    capture = LearningCapture(
        beliefs=BeliefStore(tmp_path / "beliefs.jsonl"),
        corpus=CorpusStore(tmp_path / "corpus.jsonl"),
        artifacts_store=artifacts,
    )

    _, record = capture.capture_verified_patch(
        task_id=task_id,
        artifacts=[artifact],
        rights=RightsDeclaration(
            rights_confirmed=True,
            privacy_reviewed=True,
            training_allowed=True,
            source_license="internal-approved",
        ),
    )

    assert record.status == CorpusStatus.BLOCKED
    assert record.privacy_scan.status == PrivacyScanStatus.FLAGGED


def test_layered_verified_patch_is_at_most_silver(tmp_path):
    task_id = uuid4()
    artifacts = ArtifactStore(tmp_path / "artifacts")
    records = [
        artifacts.put_text(task_id=task_id, kind="verified-patch", text="diff"),
        artifacts.put_text(
            task_id=task_id,
            kind="verification-report",
            text='{"verified":true}',
            metadata={"verified": True},
        ),
        artifacts.put_text(task_id=task_id, kind="tests-before", text="failed"),
        artifacts.put_text(task_id=task_id, kind="tests-after", text="passed"),
        artifacts.put_text(task_id=task_id, kind="syntax-check", text="ok"),
    ]
    capture = LearningCapture(
        beliefs=BeliefStore(tmp_path / "beliefs.jsonl"),
        corpus=CorpusStore(tmp_path / "corpus.jsonl"),
        artifacts_store=artifacts,
    )

    _, record = capture.capture_verified_patch(
        task_id=task_id,
        artifacts=records,
    )

    assert record.quality_tier == QualityTier.SILVER
    assert record.quality_tier not in {QualityTier.GOLD, QualityTier.PLATINUM}
