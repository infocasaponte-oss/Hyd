# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""One ledger contract, two backends (JSONL files on one host, PostgreSQL shared by every node).

PostgreSQL cases run when HYDRA_IT_POSTGRES points at a disposable server whose user may create
databases (``pg_url`` in conftest gives each test its own database: the ledger forbids TRUNCATE):
    docker run -d -p 127.0.0.1:15432:5432 -e POSTGRES_USER=hydra -e POSTGRES_PASSWORD=hydra postgres:17
    HYDRA_IT_POSTGRES=postgresql://hydra:hydra@127.0.0.1:15432/hydra
"""
from __future__ import annotations

import os
import tarfile
import threading

import pytest

from hydra.governance.recovery import backup, restore
from hydra.ledger.chain import Ledger
from hydra.ledger.signing import Signer

PG = os.environ.get("HYDRA_IT_POSTGRES")
needs_pg = pytest.mark.skipif(not PG, reason="set HYDRA_IT_POSTGRES")


@pytest.fixture
def signer():
    return Signer.generate()


@pytest.fixture(params=["file", "postgres"])
def ledger(request, tmp_path, signer):
    if request.param == "file":
        yield Ledger(tmp_path / "ledger", signer, anchor_every=4)
        return
    url = request.getfixturevalue("pg_url")
    from hydra.ledger.pg import PostgresLedger

    lg = PostgresLedger(url, signer, anchor_every=4)
    yield lg
    lg.close()


def test_append_query_anchor_proof_and_verify(ledger):
    for i in range(9):
        ledger.append("TASK_EXECUTED", {"i": i, "nested": {"b": 1.5, "a": "ñ"}}, object_type="task", object_id=f"t{i % 3}")
    corr = ledger.correct(next(ledger.events()).event_id, {"i": -1}, "typo")
    assert len(ledger) == 10 and corr.payload["reason"] == "typo"
    assert [e.sequence for e in ledger.for_object("task", "t1")] == [2, 5, 8]
    assert len(list(ledger.events("TASK_EXECUTED"))) == 9
    assert {e.sequence for e in ledger.search("t2")} >= {3, 6, 9}
    assert [(a.first_sequence, a.last_sequence) for a in ledger.anchors()] == [(1, 4), (5, 8)]
    assert ledger.anchor_now().last_sequence == 10 and ledger.anchor_now() is None
    proof = ledger.proof(6)
    assert proof["root"] == ledger.anchors()[1].merkle_root
    report = ledger.verify()
    assert report.ok and report.events == 10 and report.signatures_checked == 10


@needs_pg
def test_concurrent_writers_on_many_connections_build_one_chain(pg_url, signer):
    from hydra.ledger.pg import PostgresLedger

    PostgresLedger(pg_url, signer).close()  # schema once

    def writer(n: int) -> None:
        node = PostgresLedger(pg_url, signer, anchor_every=0)
        try:
            for i in range(25):
                node.append("TASK_EXECUTED", {"node": n, "i": i})
        finally:
            node.close()

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lg = PostgresLedger(pg_url, signer)
    report = lg.verify()
    assert report.ok and report.events == 200 and report.signatures_checked == 200
    lg.close()


@needs_pg
def test_rows_are_immutable_and_tampering_is_detected(pg_url, signer):
    import psycopg

    from hydra.ledger.pg import PostgresLedger

    lg = PostgresLedger(pg_url, signer)
    for i in range(3):
        lg.append("TASK_EXECUTED", {"i": i})
    with psycopg.connect(pg_url, autocommit=True) as con:
        for sql in ("UPDATE ip_events SET event_type = 'X' WHERE sequence_id = 2",
                    "DELETE FROM ip_events WHERE sequence_id = 2", "TRUNCATE ip_events"):
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                con.execute(sql)
        # A database superuser can still bypass the triggers: the hash chain must catch it.
        con.execute("ALTER TABLE ip_events DISABLE TRIGGER ip_events_no_update")
        con.execute("UPDATE ip_events SET body = replace(body, '\"i\":1', '\"i\":999') WHERE sequence_id = 2")
        con.execute("ALTER TABLE ip_events ENABLE TRIGGER ip_events_no_update")
    report = lg.verify()
    assert not report.ok and report.broken_at == 2 and report.reason == "event_hash mismatch"
    lg.close()


@needs_pg
def test_existing_file_ledger_is_adopted_once_and_the_chain_continues(pg_url, signer, tmp_path):
    from hydra.ledger.pg import LedgerConflict, open_ledger

    root = tmp_path / "ledger"
    file_ledger = Ledger(root, signer, anchor_every=2)
    for i in range(5):
        file_ledger.append("TASK_EXECUTED", {"i": i})
    head = list(file_ledger.events())[-1].event_hash

    pg = open_ledger("postgres", root, signer, 2, pg_url)
    assert pg.backend == "postgres" and len(pg) == 5 and list(pg.events())[-1].event_hash == head
    e = pg.append("TASK_EXECUTED", {"i": 5})
    assert e.sequence == 6 and e.previous_hash == head
    again = open_ledger("postgres", root, signer, 2, pg_url)  # restart: nothing re-imported
    assert len(again) == 6 and again.verify().ok
    assert (root / "events.jsonl").read_text(encoding="utf-8").count("\n") == 5  # file kept, not written

    other = tmp_path / "other"
    Ledger(other, signer).append("TASK_EXECUTED", {"different": True})
    with pytest.raises(LedgerConflict, match="different chains"):
        open_ledger("postgres", other, signer, 2, pg_url)
    pg.close()
    again.close()


@needs_pg
def test_backup_exports_the_postgres_ledger_and_restore_verifies_it(pg_url, signer, tmp_path):
    from hydra.ledger.pg import PostgresLedger

    data = tmp_path / "data"
    (data / "keys").mkdir(parents=True)
    (data / "keys" / "hydra-ed25519.pub.pem").write_text(signer.public_pem, encoding="utf-8")
    lg = PostgresLedger(pg_url, signer, anchor_every=3)
    for i in range(7):
        lg.append("TASK_EXECUTED", {"i": i})
    manifest = backup(data, tmp_path / "b.tar.gz", ledger=lg)
    assert manifest.ledger_events == 7 and manifest.ledger_head == list(lg.events())[-1].event_hash
    with tarfile.open(tmp_path / "b.tar.gz") as tar:
        assert "data/ledger/events.jsonl" in tar.getnames()
    report = restore(tmp_path / "b.tar.gz", tmp_path / "restored")
    assert report.ok and report.ledger["events"] == 7 and report.ledger["signatures_checked"] == 7
    lg.close()


def test_backend_selection(tmp_path, monkeypatch, signer):
    from hydra.ledger.pg import open_ledger

    assert open_ledger("auto", tmp_path / "a", signer, 10).backend == "file"
    assert open_ledger("file", tmp_path / "b", signer, 10, "postgresql://ignored").backend == "file"
    with pytest.raises(ValueError, match="requires HYDRA_POSTGRES_URL"):
        open_ledger("postgres", tmp_path / "c", signer, 10)
    with pytest.raises(ValueError, match="unknown ledger backend"):
        open_ledger("s3", tmp_path / "d", signer, 10)
    import builtins

    real_import = builtins.__import__

    def no_psycopg(name, *a, **kw):
        if name == "psycopg":
            raise ImportError("psycopg")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_psycopg)
    assert open_ledger("auto", tmp_path / "e", signer, 10, "postgresql://x").backend == "file"
    with pytest.raises(RuntimeError, match="psycopg"):
        open_ledger("postgres", tmp_path / "f", signer, 10, "postgresql://x")


@needs_pg
def test_backup_carries_both_the_postgres_ledger_and_keyring_keys(pg_url, tmp_path):
    from hydra.core.keystore import KeyStore
    from hydra.ledger.pg import PostgresLedger

    class MemoryKeyring:
        priority = 5

        def __init__(self):
            self.items = {}

        def get_password(self, service, user):
            return self.items.get((service, user))

        def set_password(self, service, user, value):
            self.items[(service, user)] = value

    data = tmp_path / "data"
    store = KeyStore(data, keyring_backend=MemoryKeyring(), namespace="bk")
    node_signer = Signer.load_or_create(data / "keys", keystore=store)
    lg = PostgresLedger(pg_url, node_signer)
    for i in range(3):
        lg.append("TASK_EXECUTED", {"i": i})
    backup(data, tmp_path / "full.tar.gz", include_private_keys=True, keystore=store, ledger=lg)
    with tarfile.open(tmp_path / "full.tar.gz") as tar:
        names = set(tar.getnames())
        key_mode = tar.getmember("data/keys/hydra-ed25519.pem").mode
    assert {"data/ledger/events.jsonl", "data/keys/hydra-ed25519.pem"} <= names and key_mode == 0o600
    report = restore(tmp_path / "full.tar.gz", tmp_path / "restored")
    assert report.ok and report.ledger["signatures_checked"] == 3
    lg.close()
