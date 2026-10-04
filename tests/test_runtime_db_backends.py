# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""F3c: the runtime-line stores of ``hydra.db`` on SQLite and on PostgreSQL (same contract).

PostgreSQL cases need HYDRA_IT_POSTGRES (``pg_url`` in conftest gives each test its own database)."""
from __future__ import annotations

import threading
from uuid import uuid4

import pytest

from hydra.runtime.capture_uow import CaptureUnitOfWork, TaskCommit
from hydra.runtime.circuit_breaker import CircuitState
from hydra.runtime.deployment_evidence import CanaryEvidence, ShadowEvidence
from hydra.runtime.deployment_evidence_store import DeploymentEvidenceStore
from hydra.runtime.metrics_store import OperatingMetricsStore
from hydra.runtime.operating_metrics import OperatingMetrics
from hydra.runtime.outbox_metrics import collect_outbox_metrics
from hydra.runtime.outbox_worker import OutboxWorker
from hydra.runtime.pg_stores import PostgresOperatingMetricsStore, PostgresRuntimeHealthStore, open_runtime_stores
from hydra.runtime.runtime_health import RuntimeHealth
from hydra.runtime.runtime_health_store import RuntimeHealthStore


@pytest.fixture(params=["sqlite", "postgres"])
def stores(request, tmp_path):
    url = request.getfixturevalue("pg_url") if request.param == "postgres" else ""
    return open_runtime_stores(tmp_path / "hydra.db", url)


def _commit(uow, *, corpus=True):
    task_id = uuid4()
    uow.commit_terminal(TaskCommit(task_id=task_id, trace_id="trace", status="completed", result={"answer": "ok"}),
                        event_payload={"event_type": "hydra.task.completed", "payload": {}},
                        provenance_payload={"action": "task.completed", "outputs": {}},
                        corpus_payload={"record_id": "candidate"} if corpus else None)
    return task_id


def _metrics(n=1):
    return OperatingMetrics(outbox_pending=n, outbox_dead_letters=0, oldest_pending_age_seconds=None, spans_total=4,
                            spans_error=1, avg_span_duration_ms=12.5, spans_by_name={"routing": 2},
                            deployments_by_state={"active": 1})


def test_runtime_store_contract(stores):
    uow = stores.capture_uow
    task_id = _commit(uow)
    restored = uow.get_task_commit(task_id)
    assert restored.status == "completed" and restored.result == {"answer": "ok"}
    assert uow.get_task_commit(uuid4()) is None
    summary = collect_outbox_metrics(uow.outbox)
    assert summary.pending == 3 and summary.dead_letters == 0 and summary.oldest_pending_age_seconds is not None
    assert collect_outbox_metrics(uow.outbox).pending == 3  # measuring claims nothing
    assert [m.topic for m in uow.outbox.pending()] == ["event", "provenance", "corpus"]

    evidence = stores.deployment_evidence
    evidence.append_shadow("v", ShadowEvidence(samples=10, agreement_rate=1.0, error_rate=0.0))
    evidence.append_canary("v", CanaryEvidence(requests=5, error_rate=0.0, p95_latency_ms=12.0))
    evidence.append_canary("v", CanaryEvidence(requests=9, error_rate=0.0, p95_latency_ms=11.0))
    assert evidence.latest_canary("v").requests == 9 and evidence.latest_shadow("v").samples == 10
    assert evidence.latest_shadow("other") is None

    metrics = stores.operating_metrics
    first = metrics.append(_metrics(1))
    second = metrics.append(_metrics(2))
    rows = metrics.recent()
    assert [r["id"] for r in rows] == [second, first] and rows[0]["metrics"]["outbox_pending"] == 2
    with pytest.raises(ValueError):
        metrics.recent(0)

    health = RuntimeHealth(store=stores.runtime_health)
    for _ in range(3):
        health.failure("variant-1")
    assert RuntimeHealth(store=stores.runtime_health).breaker_for("variant-1").state == CircuitState.OPEN


def test_a_failed_commit_writes_nothing(pg_url, tmp_path):
    uow = open_runtime_stores(tmp_path / "hydra.db", pg_url).capture_uow
    task_id = uuid4()
    with pytest.raises(TypeError):  # payload that cannot be stored aborts the whole transaction
        uow.commit_terminal(TaskCommit(task_id=task_id, trace_id="t", status="completed", result={}),
                            event_payload={"bad": object()}, provenance_payload={})
    assert uow.get_task_commit(task_id) is None and collect_outbox_metrics(uow.outbox).pending == 0


def test_nodes_never_dispatch_the_same_runtime_message_twice(pg_url, tmp_path):
    nodes = [open_runtime_stores(tmp_path / f"n{k}.db", pg_url) for k in range(4)]
    for _ in range(15):
        _commit(nodes[0].capture_uow, corpus=False)  # 30 messages
    dispatched, lock = [], threading.Lock()

    class Dispatcher:
        def _dispatch(self, message):
            with lock:
                dispatched.append(message.id)

    def drain(stores):
        worker = OutboxWorker(stores.capture_uow.outbox, Dispatcher())
        while worker.run_once(4).published:
            pass

    threads = [threading.Thread(target=drain, args=(n,)) for n in nodes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(dispatched) == len(set(dispatched)) == 30


def test_breakers_belong_to_their_node(pg_url, tmp_path):
    a = open_runtime_stores(tmp_path / "a.db", pg_url)
    b_store = PostgresRuntimeHealthStore(a.runtime_health.db, node="other-node")
    health = RuntimeHealth(store=a.runtime_health)
    for _ in range(3):
        health.failure("variant-1")
    assert RuntimeHealth(store=b_store).breaker_for("variant-1").state == CircuitState.CLOSED


def test_metrics_history_is_bounded(pg_url, tmp_path):
    db = open_runtime_stores(tmp_path / "hydra.db", pg_url).operating_metrics.db
    store = PostgresOperatingMetricsStore(db, max_snapshots=3)
    ids = [store.append(_metrics(i)) for i in range(5)]
    assert [r["id"] for r in store.recent()] == ids[:-4:-1]


def test_existing_hydra_db_is_imported_once(pg_url, tmp_path):
    path = tmp_path / "hydra.db"
    uow = CaptureUnitOfWork(path)
    task_id = _commit(uow, corpus=False)
    published = uow.outbox.pending(1)[0]
    uow.outbox.mark_published(published.id)
    DeploymentEvidenceStore(path).append_canary("v", CanaryEvidence(requests=7, error_rate=0.0, p95_latency_ms=1.0))
    OperatingMetricsStore(path).append(_metrics(4))
    legacy_health = RuntimeHealth(store=RuntimeHealthStore(path))
    for _ in range(3):
        legacy_health.failure("variant-1")

    shared = open_runtime_stores(path, pg_url)
    assert shared.capture_uow.get_task_commit(task_id).status == "completed"
    assert collect_outbox_metrics(shared.capture_uow.outbox).pending == 1  # the published one is not replayed
    assert shared.deployment_evidence.latest_canary("v").requests == 7
    assert shared.operating_metrics.recent()[0]["metrics"]["outbox_pending"] == 4
    assert RuntimeHealth(store=shared.runtime_health).breaker_for("variant-1").state == CircuitState.OPEN
    again = open_runtime_stores(path, pg_url)  # a second start imports nothing twice
    assert len(again.operating_metrics.recent()) == 1 and collect_outbox_metrics(again.capture_uow.outbox).pending == 1
