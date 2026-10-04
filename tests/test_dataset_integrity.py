# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import random

import pytest

from hydra.corpus.factory import DatasetFactory, DatasetSpec
from hydra.corpus.records import CorpusRecord, RecordType
from hydra.corpus.store import CorpusStore


@pytest.mark.parametrize("values", [
    {"name": "../escape"}, {"name": "ok", "version": "../escape"},
    {"name": "ok", "splits": {"../escape": 1}},
    {"name": "ok", "splits": {"train": 0}},
    {"name": "ok", "splits": {"train": float("nan")}},
    {"name": "ok", "splits": {"holdout": 1}},
])
def test_reject_unsafe_specs(values):
    with pytest.raises(ValueError):
        DatasetSpec(**values)


def test_release_is_immutable_and_failed_build_is_not_published(tmp_path, monkeypatch):
    factory = DatasetFactory(CorpusStore(tmp_path))
    spec = DatasetSpec(name="frozen", format="raw")
    release = factory.build(spec, snapshot=False)
    before = (tmp_path / "releases" / release.id / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        factory.build(spec, snapshot=False)
    assert (tmp_path / "releases" / release.id / "manifest.json").read_bytes() == before
    monkeypatch.setattr(factory, "select", lambda _: (_ for _ in ()).throw(ValueError("failed")))
    with pytest.raises(ValueError):
        factory.build(DatasetSpec(name="failed"))
    assert not (tmp_path / "releases" / "failed-v1").exists()
    assert not list((tmp_path / "releases").glob(".building-*"))


def test_anchor_family_stays_together_and_holdout_wins(tmp_path):
    factory = DatasetFactory(CorpusStore(tmp_path))
    records = [CorpusRecord(id="anchor", record_type=RecordType.SFT),
               CorpusRecord(id="paraphrase", record_type=RecordType.SFT,
                            synthetic=True, provenance={"source_records": ["anchor"]}),
               CorpusRecord(id="paraphrase2", record_type=RecordType.SFT,
                            provenance={"source_records": ["paraphrase"]}, flags=["adversarial"])]
    parts = factory.split(records, DatasetSpec(name="family"))
    assert {r.id for r in parts["adversarial_holdout"]} == {r.id for r in records}
    assert not parts["train"] and not parts["test"]


def test_required_bucket_cannot_silently_disappear():
    records = [CorpusRecord(record_type=RecordType.SFT, language="es")]
    with pytest.raises(ValueError, match="coverage missing"):
        DatasetFactory._quota(records, lambda r: r.language, {"es": .5, "en": .5}, random.Random(17))
