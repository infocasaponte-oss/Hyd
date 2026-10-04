# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

import pytest

from hydra.runtime.corpus import CorpusRecord, CorpusStatus, RightsDeclaration
from hydra.runtime.dataset_factory import DatasetFactory


def curated_record(content_hash: str) -> CorpusRecord:
    return CorpusRecord(
        task_id=uuid4(),
        belief_id=uuid4(),
        artifact_hashes=["a"],
        status=CorpusStatus.CURATED,
        rights=RightsDeclaration(
            rights_confirmed=True, privacy_reviewed=True, training_allowed=True
        ),
        content_hash=content_hash,
    )


def test_release_rejects_quarantined_record(tmp_path):
    record = curated_record("a" * 64)
    record.status = CorpusStatus.QUARANTINED
    with pytest.raises(ValueError):
        DatasetFactory(tmp_path).release("bad", [record])


def test_release_rejects_duplicate_content(tmp_path):
    with pytest.raises(ValueError):
        DatasetFactory(tmp_path).release(
            "dupe", [curated_record("a" * 64), curated_record("a" * 64)]
        )


def test_release_has_manifest_hash(tmp_path):
    manifest = DatasetFactory(tmp_path).release("sft-alpha", [curated_record("b" * 64)])
    assert len(manifest.manifest_hash) == 64
