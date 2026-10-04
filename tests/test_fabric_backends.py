# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""One contract, two Execution Fabric backends (SQLite on one host, PostgreSQL across nodes).

PostgreSQL cases run when HYDRA_IT_POSTGRES points at a disposable database, e.g.
    docker run -d -p 127.0.0.1:15432:5432 -e POSTGRES_USER=hydra -e POSTGRES_PASSWORD=hydra postgres:17
    HYDRA_IT_POSTGRES=postgresql://hydra:hydra@127.0.0.1:15432/hydra
"""
from __future__ import annotations

import os
import threading
import time
import uuid

import pytest

from hydra.cluster.fabric import Priority, WorkItem, WorkQueue, open_work_queue, run_fabric_worker

PG = os.environ.get("HYDRA_IT_POSTGRES")


@pytest.fixture(params=["sqlite", "postgres"])
def queue(request, tmp_path):
    if request.param == "sqlite":
        yield WorkQueue(tmp_path / "q.db")
        return
    if not PG:
        pytest.skip("set HYDRA_IT_POSTGRES to run the PostgreSQL fabric")
    pytest.importorskip("psycopg")
    from hydra.cluster.fabric_pg import PostgresWorkQueue

    q = PostgresWorkQueue(PG)
    with q._con().transaction():
        q._con().execute("TRUNCATE fabric_work, fabric_idempotency, fabric_checkpoints")
    yield q
    q.close()


def cap() -> str:
    return f"cap-{uuid.uuid4().hex[:8]}"


def test_priority_lease_expiry_and_idempotency(queue):
    c = cap()
    queue.submit(WorkItem(capability=c, priority=Priority.BACKGROUND_LAB, idempotency_key="lab"))
    queue.submit(WorkItem(capability=c, priority=Priority.INTERACTIVE, idempotency_key="user"))
    first = queue.claim([c], "w1", lease_s=0.2)
    assert first.priority == Priority.INTERACTIVE
    time.sleep(0.3)
    again = queue.claim([c], "w2", lease_s=5)
    assert again.id == first.id and again.attempts == 2  # expired lease -> re-delivered
    assert not queue.complete(again.id, "w1", {"late": True})  # the old owner lost the lease
    assert queue.complete(again.id, "w2", {"answer": 42})
    assert queue.submit(WorkItem(capability=c, idempotency_key="user")).result == {"answer": 42}
    assert queue.idempotent_result("user") == {"answer": 42}


def test_background_waits_while_interactive_work_is_queued(queue):
    c, other = cap(), cap()
    queue.submit(WorkItem(capability=c, priority=Priority.BACKGROUND_LAB))
    queue.submit(WorkItem(capability=other, priority=Priority.INTERACTIVE))
    assert queue.claim([c], "w") is None  # lab work is not handed out while users wait
    assert queue.claim([c], "w", allow_background_when_busy=True).priority == Priority.BACKGROUND_LAB


def test_duplicate_open_submission_returns_the_same_job(queue):
    c = cap()
    a = queue.submit(WorkItem(capability=c, idempotency_key="k"))
    b = queue.submit(WorkItem(capability=c, idempotency_key="k"))
    assert a.id == b.id and queue.get(a.id).status == "queued"


def test_failures_back_off_then_dead_letter(queue):
    c = cap()
    item = queue.submit(WorkItem(capability=c, max_attempts=2))
    w = queue.claim([c], "w")
    before = time.time()  # measured before the call: slow CI runners must not make this flaky
    failed = queue.fail(w.id, "w", "boom", retry_in_s=0.5)
    assert failed.status == "queued" and failed.available_at >= before + 0.5
    assert queue.claim([c], "w") is None  # still backing off
    time.sleep(max(0.0, failed.available_at - time.time()) + 0.05)
    w = queue.claim([c], "w")
    assert queue.fail(w.id, "w", "boom again").status == "dead"
    assert queue.get(item.id).status == "dead" and queue.stats()["dead"]


def test_renew_and_checkpoints(queue):
    c = cap()
    queue.submit(WorkItem(capability=c))
    w = queue.claim([c], "w", lease_s=0.2)
    assert queue.renew(w.id, "w", lease_s=5) and not queue.renew(w.id, "intruder")
    time.sleep(0.3)
    assert queue.claim([c], "other") is None  # renewed lease still holds
    queue.checkpoint("long", 1, {"s": 1})
    queue.checkpoint("long", 2, {"s": 2})
    assert queue.last_checkpoint("long") == (2, {"s": 2}) and queue.last_checkpoint("none") is None


async def test_worker_loop(queue):
    c = cap()
    queue.submit(WorkItem(capability=c))

    async def handler(item):
        return {"ok": item.capability}

    assert await run_fabric_worker(queue, [c], handler, once=True) == 1
    assert queue.stats()["done"]


@pytest.mark.skipif(not PG, reason="set HYDRA_IT_POSTGRES")
def test_concurrent_workers_on_different_connections_never_share_a_job(queue):
    if queue.backend != "postgres":
        pytest.skip("multi-node concurrency applies to the PostgreSQL fabric")
    from hydra.cluster.fabric_pg import PostgresWorkQueue

    c = cap()
    jobs = {queue.submit(WorkItem(capability=c)).id for _ in range(60)}
    claimed: list[str] = []
    lock = threading.Lock()

    def worker(n: int) -> None:
        node = PostgresWorkQueue(PG)  # one connection per "node"
        try:
            while (w := node.claim([c], f"node-{n}")) is not None:
                with lock:
                    claimed.append(w.id)
                node.complete(w.id, f"node-{n}", {"by": n})
        finally:
            node.close()

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(claimed) == sorted(jobs)  # every job exactly once
    assert queue.stats()["done"]["NORMAL"] == 60


@pytest.mark.skipif(not PG, reason="set HYDRA_IT_POSTGRES")
def test_concurrent_idempotent_submissions_create_one_job(queue):
    if queue.backend != "postgres":
        pytest.skip("multi-node concurrency applies to the PostgreSQL fabric")
    from hydra.cluster.fabric_pg import PostgresWorkQueue

    c = cap()
    ids: list[str] = []
    lock = threading.Lock()

    def producer() -> None:
        node = PostgresWorkQueue(PG)
        try:
            item = node.submit(WorkItem(capability=c, idempotency_key="charge-card-42"))
            with lock:
                ids.append(item.id)
        finally:
            node.close()

    threads = [threading.Thread(target=producer) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(ids)) == 1


def test_backend_selection(tmp_path, monkeypatch):
    assert open_work_queue("auto", tmp_path / "a.db").backend == "sqlite"
    assert open_work_queue("sqlite", tmp_path / "b.db", "postgresql://ignored").backend == "sqlite"
    with pytest.raises(ValueError, match="requires HYDRA_POSTGRES_URL"):
        open_work_queue("postgres", tmp_path / "c.db")
    with pytest.raises(ValueError, match="unknown fabric backend"):
        open_work_queue("redis", tmp_path / "d.db")
    import builtins

    real_import = builtins.__import__

    def no_psycopg(name, *a, **kw):
        if name == "psycopg":
            raise ImportError("psycopg")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_psycopg)
    assert open_work_queue("auto", tmp_path / "e.db", "postgresql://x").backend == "sqlite"  # warned fallback
    with pytest.raises(RuntimeError, match="psycopg"):
        open_work_queue("postgres", tmp_path / "f.db", "postgresql://x")
