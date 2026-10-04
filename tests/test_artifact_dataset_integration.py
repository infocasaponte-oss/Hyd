# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import importlib
from uuid import uuid4

import pytest

from hydra.corpus.artifact_candidates import CorpusRecord, CorpusStatus
from hydra.corpus.artifact_datasets import DatasetManifest
from hydra.corpus.factory import DatasetFactory
from hydra.corpus.store import CorpusStore


@pytest.mark.parametrize("old,new", [
    ("hydra.runtime.dataset_factory", "hydra.corpus.artifact_datasets"),
    ("hydra.runtime.corpus_quality", "hydra.corpus.patch_quality"),
])
def test_old_module_is_canonical(old, new):
    assert importlib.import_module(old) is importlib.import_module(new)


def _record(status=CorpusStatus.CURATED, digest="a" * 64):
    return CorpusRecord(task_id=uuid4(), belief_id=uuid4(), artifact_hashes=["b" * 64],
                        status=status, content_hash=digest)


def test_platform_factory_releases_artifact_manifest_with_old_schema(tmp_path):
    factory = DatasetFactory(CorpusStore(tmp_path / "corpus"))
    record = _record()
    manifest = factory.release_artifacts("artifact-release", [record], root=tmp_path)
    saved = DatasetManifest.model_validate_json(
        (tmp_path / f"{manifest.dataset_id}.manifest.json").read_text()
    )
    assert saved == manifest
    assert saved.record_ids == [record.record_id]
    assert saved.record_hashes == [record.content_hash]
    assert len(saved.manifest_hash) == 64


@pytest.mark.parametrize("status", [CorpusStatus.QUARANTINED, CorpusStatus.BLOCKED, CorpusStatus.TOMBSTONED])
def test_platform_artifact_release_rejects_non_curated_without_manifest(tmp_path, status):
    with pytest.raises(ValueError, match="only CURATED"):
        DatasetFactory(CorpusStore(tmp_path / "corpus")).release_artifacts("rejected", [_record(status)], root=tmp_path)
    assert not list(tmp_path.glob("*.manifest.json"))


def test_platform_artifact_release_rejects_duplicates_without_manifest(tmp_path):
    with pytest.raises(ValueError, match="Duplicate"):
        DatasetFactory(CorpusStore(tmp_path / "corpus")).release_artifacts("duplicate", [_record(), _record()], root=tmp_path)
    assert not list(tmp_path.glob("*.manifest.json"))
