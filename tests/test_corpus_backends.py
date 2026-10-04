# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Event logs and the corpus on them: JSONL files on one node, PostgreSQL ``hydra_logs`` shared by all.

PostgreSQL cases run when HYDRA_IT_POSTGRES points at a disposable server whose user may create
databases (``pg_url`` in conftest gives each test its own database), e.g.
    docker run -d -p 127.0.0.1:15432:5432 -e POSTGRES_USER=hydra -e POSTGRES_PASSWORD=hydra postgres:17
    HYDRA_IT_POSTGRES=postgresql://hydra:hydra@127.0.0.1:15432/hydra
"""
from __future__ import annotations

import json
import tarfile
import threading

import pytest

from hydra.core.eventlog import FileLog, LogConflict, LogSpace, open_log_space
from hydra.corpus.records import CorpusRecord, RecordType, RightsMetadata, TrainingStatus
from hydra.corpus.store import CorpusStore
from hydra.governance.recovery import backup, restore


def record(i: int, quality: float = 0.95) -> CorpusRecord:
    return CorpusRecord(record_type=RecordType.SFT, input={"prompt": f"pregunta {i} sobre la arquitectura de HYDRA"},
                        output={"answer": f"respuesta detallada número {i}"}, quality=quality, verification=0.95,
                        rights=RightsMetadata(training_allowed=True))


@pytest.fixture(params=["file", "postgres"])
def space(request):
    if request.param == "file":
        yield LogSpace(label="corpus")
        return
    s = LogSpace(request.getfixturevalue("pg_url"), label="corpus")
    yield s
    s.close()


# ---------------------------------------------------------------------------------- event log
def test_log_contract(space, tmp_path):
    log = space.open(tmp_path / "a.jsonl", "corpus/a.jsonl")
    assert len(log) == 0 and list(log.read()) == []
    for i in range(5):
        assert log.append(json.dumps({"i": i})) == (i + 1, json.dumps({"i": i}))
    seq, body = log.append(lambda n, last: json.dumps({"n": n, "prev": json.loads(last)["i"]}))
    assert (seq, json.loads(body)) == (6, {"n": 6, "prev": 4})
    assert len(log) == 6
    assert [s for s, _ in log.read(2, 4)] == [3, 4]
    assert log.export_text().count("\n") == 6
    with pytest.raises(ValueError):
        log.append('{"a":\n1}')


def test_file_log_ignores_blank_lines_and_counts_like_before(tmp_path):
    path = tmp_path / "log.jsonl"
    path.write_text('{"a":1}\n\n{"a":2}\n', encoding="utf-8")
    log = FileLog(path)
    assert len(log) == 2 and log.append('{"a":3}')[0] == 3
    assert [s for s, _ in log.read()] == [1, 2, 3]


def test_concurrent_appends_produce_one_gap_free_order(pg_url, tmp_path):
    spaces = [LogSpace(pg_url, label="corpus") for _ in range(4)]
    logs = [s.open(tmp_path / "x.jsonl", "corpus/x.jsonl") for s in spaces]

    def writer(k):
        for i in range(25):
            logs[k].append(json.dumps({"w": k, "i": i}))

    threads = [threading.Thread(target=writer, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [s for s, _ in logs[0].read()] == list(range(1, 101))
    for s in spaces:
        s.close()


def test_rows_are_append_only(pg_url, tmp_path):
    psycopg = pytest.importorskip("psycopg")
    space = LogSpace(pg_url, label="corpus")
    space.open(tmp_path / "x.jsonl", "corpus/x.jsonl").append("{}")
    with psycopg.connect(pg_url, autocommit=True) as con:
        for sql in ("UPDATE hydra_logs SET body = '[]'", "DELETE FROM hydra_logs", "TRUNCATE hydra_logs"):
            with pytest.raises(psycopg.errors.RaiseException):
                con.execute(sql)
    space.close()


def test_file_log_is_imported_once_and_a_different_history_is_refused(pg_url, tmp_path):
    path = tmp_path / "corpus" / "log.jsonl"
    path.parent.mkdir()
    path.write_text('{"a":1}\n{"a":2}\n', encoding="utf-8")
    space = LogSpace(pg_url, label="corpus")
    log = space.open(path, "corpus/log.jsonl")
    assert [b for _, b in log.read()] == ['{"a":1}', '{"a":2}']
    log.append('{"a":3}')
    assert len(space.open(path, "corpus/log.jsonl")) == 3  # reopening imports nothing
    path.write_text('{"a":1}\n{"a":9}\n', encoding="utf-8")
    with pytest.raises(LogConflict):
        space.open(path, "corpus/log.jsonl")
    space.close()


def test_backend_selection(monkeypatch):
    assert open_log_space("file", "postgresql://ignored", "corpus").backend == "file"
    assert open_log_space("auto", "", "corpus").backend == "file"
    with pytest.raises(ValueError, match="HYDRA_CORPUS_BACKEND=postgres requires"):
        open_log_space("postgres", "", "corpus")
    with pytest.raises(ValueError, match="unknown"):
        open_log_space("sqlite", "", "corpus")
    import builtins

    real_import = builtins.__import__

    def no_psycopg(name, *a, **kw):
        if name == "psycopg":
            raise ImportError(name)
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_psycopg)
    assert open_log_space("auto", "postgresql://x/y", "corpus").backend == "file"
    with pytest.raises(RuntimeError, match="needs psycopg"):
        open_log_space("postgres", "postgresql://x/y", "corpus")


# ---------------------------------------------------------------------------------- corpus
def test_corpus_contract_on_both_backends(space, tmp_path):
    store = CorpusStore(tmp_path / "corpus", logs=space)
    good = store.ingest(record(1))[0]
    assert good.training_status == TrainingStatus.GOLD
    assert store.ingest(good.model_copy(update={"id": "dup"}))[0].training_status == TrainingStatus.DUPLICATE
    store.add_lineage(good.id, "dataset:d1", "dataset_release")
    snap = store.snapshot()
    store.tombstone(good.id, "owner request")
    second = store.snapshot()
    assert second.parent == snap.id and second.id.endswith("-2")
    assert store.at_snapshot(snap.id)[good.id].training_status == TrainingStatus.GOLD
    reopened = CorpusStore(tmp_path / "corpus", logs=space)
    assert reopened.get(good.id).training_status == TrainingStatus.TOMBSTONED
    assert reopened.tombstones[good.id].affected_datasets == ["dataset:d1"]
    assert reopened.stats()["records"] == store.stats()["records"] == 2
    assert [json.loads(line)["id"] for _, line in reopened.history(2)] == [good.id]


def test_two_nodes_share_one_corpus(pg_url, tmp_path):
    a = CorpusStore(tmp_path / "a", logs=LogSpace(pg_url, label="corpus"), refresh_s=0)
    b = CorpusStore(tmp_path / "b", logs=LogSpace(pg_url, label="corpus"), refresh_s=0)
    rec = a.ingest(record(1))[0]
    assert b.get(rec.id).training_status == TrainingStatus.GOLD
    # b's dedup index learned a's record: the same content is a duplicate on b too
    assert b.ingest(rec.model_copy(update={"id": "copy"}))[0].training_status == TrainingStatus.DUPLICATE
    b.add_lineage(rec.id, "dataset:d1", "dataset_release")
    t = a.tombstone(rec.id, "owner request")
    assert t.affected_datasets == ["dataset:d1"]
    assert b.get(rec.id).training_status == TrainingStatus.TOMBSTONED
    s1, s2 = a.snapshot(), b.snapshot()
    assert s1.id != s2.id and s2.parent == s1.id
    assert a.offset == b.offset and a.stats() == b.stats()


def test_reads_are_refreshed_at_most_every_refresh_s(pg_url, tmp_path):
    a = CorpusStore(tmp_path / "a", logs=LogSpace(pg_url, label="corpus"), refresh_s=0)
    b = CorpusStore(tmp_path / "b", logs=LogSpace(pg_url, label="corpus"), refresh_s=3600)
    rec = a.ingest(record(1))[0]
    assert b.get(rec.id) is None  # within the refresh window
    b.add_lineage(rec.id, "dataset:d1", "x")  # a write replays everything before it
    assert b.get(rec.id) is not None


def test_backup_exports_the_postgres_corpus_and_restore_rebuilds_it(pg_url, tmp_path):
    space = LogSpace(pg_url, label="corpus")
    data = tmp_path / "data"
    store = CorpusStore(data / "corpus", logs=space)
    for i in range(3):
        store.ingest(record(i))
    store.snapshot()
    manifest = backup(data, tmp_path / "b.tar.gz", logs=[space])
    assert {"corpus/log.jsonl", "corpus/snapshots.jsonl"} <= set(manifest.files)
    with tarfile.open(tmp_path / "b.tar.gz") as tar:
        assert "data/corpus/log.jsonl" in tar.getnames()
    report = restore(tmp_path / "b.tar.gz", tmp_path / "restored")
    assert report.ok and report.corpus_records == 3
    # the restored files and the PostgreSQL streams hold the same history: reopening imports nothing
    fresh = CorpusStore(tmp_path / "restored" / "corpus", logs=LogSpace(pg_url, label="corpus"))
    assert len(fresh.records) == 3
    space.close()
