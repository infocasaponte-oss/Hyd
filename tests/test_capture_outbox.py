# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from hydra.core.capture_outbox import CaptureOutbox
from hydra.core.contracts import HydraRequest, Message
from hydra.runtime.outbox_worker import RetryPolicy


def _ask(text: str) -> HydraRequest:
    return HydraRequest(messages=[Message(role="user", content=text)], use_cache=False)


async def test_failed_ledger_write_is_deferred_and_replayed(runtime, monkeypatch):
    ledger = runtime.ledger
    real_append = ledger.append
    calls = {"n": 0}

    def flaky(event_type, payload, **options):
        if event_type == "TASK_EXECUTED" and calls["n"] == 0:
            calls["n"] += 1
            raise OSError("disk full")
        return real_append(event_type, payload, **options)

    monkeypatch.setattr(ledger, "append", flaky)
    response = await runtime.kernel.run(_ask("¿Cuánto es 20+22?"))
    task_id = response.meta.task_id
    assert "ledger" in response.learning["deferred"]
    assert runtime.capture_outbox.stats()["pending"] == 1
    assert not any(e.payload.get("task") == task_id for e in ledger.events())

    result = runtime.capture_outbox.drain()
    assert result.published == 1 and runtime.capture_outbox.stats()["pending"] == 0
    replayed = [e for e in ledger.events() if e.event_type == "TASK_EXECUTED" and e.payload.get("task") == task_id]
    assert len(replayed) == 1 and ledger.verify().ok


async def test_capture_without_failures_defers_nothing(runtime):
    response = await runtime.kernel.run(_ask("¿Cuánto es 1+1?"))
    assert "deferred" not in response.learning
    assert runtime.capture_outbox.stats() == {"pending": 0, "dead_letters": 0}


def test_capture_outbox_is_visible_through_the_api(settings):
    from fastapi.testclient import TestClient

    from hydra.api.main import create_app

    with TestClient(create_app(settings)) as client:
        assert client.get("/hydra/v1/capture/outbox").json() == {"pending": 0, "dead_letters": 0, "messages": []}


def test_persistent_failure_ends_in_dead_letter_queue(tmp_path):
    class BrokenLedger:
        def append(self, *args, **kwargs):
            raise OSError("read-only filesystem")

    outbox = CaptureOutbox(tmp_path / "capture_outbox.db", ledger=BrokenLedger(),
                           policy=RetryPolicy(max_attempts=2, base_delay_seconds=0))
    outbox.defer("capture.ledger", "task-1", {"event_type": "TASK_EXECUTED", "payload": {"task": "task-1"}})
    assert outbox.drain().retried == 1
    assert outbox.drain().dead_lettered == 1
    assert outbox.stats() == {"pending": 0, "dead_letters": 1}
    [dead] = outbox.dead_letters()
    assert dead["topic"] == "capture.ledger" and "read-only" in dead["last_error"]


# ---------------------------------------------------------------------------------- shared store
import threading  # noqa: E402
from uuid import UUID  # noqa: E402

import pytest  # noqa: E402

from hydra.core.capture_outbox_pg import PostgresOutbox, open_outbox_store  # noqa: E402
from hydra.runtime.outbox import TransactionalOutbox  # noqa: E402


class CountingLedger:
    def __init__(self):
        self.events, self._lock = [], threading.Lock()

    def append(self, event_type, payload, **options):
        with self._lock:
            self.events.append(payload["task"])


@pytest.fixture(params=["sqlite", "postgres"])
def store(request, tmp_path):
    if request.param == "sqlite":
        yield TransactionalOutbox(tmp_path / "capture_outbox.db")
        return
    s = PostgresOutbox(request.getfixturevalue("pg_url"))
    yield s
    s.close()


def test_outbox_contract_on_both_stores(store, tmp_path):
    ledger = CountingLedger()
    outbox = CaptureOutbox(tmp_path / "unused.db", ledger=ledger, store=store,
                           policy=RetryPolicy(max_attempts=2, base_delay_seconds=0))
    for i in range(3):
        outbox.defer("capture.ledger", f"task-{i}", {"event_type": "TASK_EXECUTED", "payload": {"task": i}})
    outbox.defer("capture.unknown", "task-x", {})
    assert outbox.stats() == {"pending": 4, "dead_letters": 0}
    assert outbox.stats()["pending"] == 4  # counting claims nothing
    assert outbox.drain().published == 3 and ledger.events == [0, 1, 2]
    assert outbox.drain().dead_lettered == 1
    assert outbox.stats() == {"pending": 0, "dead_letters": 1}
    [dead] = outbox.dead_letters()
    assert "Unknown capture outbox topic" in dead["last_error"]
    assert store.requeue_dead_letter(UUID(dead["id"]))
    assert outbox.stats() == {"pending": 1, "dead_letters": 0}


def test_nodes_never_replay_the_same_message_twice(pg_url, tmp_path):
    ledger = CountingLedger()
    nodes = [CaptureOutbox(tmp_path / "unused.db", ledger=ledger, store=PostgresOutbox(pg_url)) for _ in range(4)]
    for i in range(60):
        nodes[0].defer("capture.ledger", f"task-{i}", {"event_type": "TASK_EXECUTED", "payload": {"task": i}})

    def drain(node):
        while node.drain(limit=5).published:
            pass

    threads = [threading.Thread(target=drain, args=(n,)) for n in nodes]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(ledger.events) == list(range(60))
    assert nodes[1].stats() == {"pending": 0, "dead_letters": 0}


def test_a_claim_expires_when_its_node_dies(pg_url, tmp_path):
    crashed = PostgresOutbox(pg_url, lease_s=0.2)
    with crashed.transaction() as con:
        crashed.enqueue(con, topic="capture.ledger", aggregate_id=UUID(int=1), trace_id="t",
                        payload={"event_type": "TASK_EXECUTED", "payload": {"task": 7}})
    assert len(crashed.pending()) == 1  # claimed, then the node "dies"
    survivor = PostgresOutbox(pg_url)
    assert survivor.pending() == []
    import time

    time.sleep(0.3)
    assert len(survivor.pending()) == 1


def test_sqlite_messages_are_imported_once(pg_url, tmp_path):
    path = tmp_path / "capture_outbox.db"
    local = CaptureOutbox(path)
    local.defer("capture.ledger", "task-1", {"event_type": "TASK_EXECUTED", "payload": {"task": 1}})
    local.defer("capture.ledger", "task-2", {"event_type": "TASK_EXECUTED", "payload": {"task": 2}})
    local.outbox.mark_published(local.outbox.pending(1)[0].id)
    shared = open_outbox_store("auto", path, pg_url)
    assert isinstance(shared, PostgresOutbox) and shared.counts() == {"pending": 1, "dead_letters": 0}
    assert open_outbox_store("auto", path, pg_url).counts()["pending"] == 1  # not imported again


def test_outbox_backend_selection(tmp_path):
    assert isinstance(open_outbox_store("auto", tmp_path / "o.db", ""), TransactionalOutbox)
    assert isinstance(open_outbox_store("sqlite", tmp_path / "o.db", "postgresql://x/y"), TransactionalOutbox)
    with pytest.raises(ValueError, match="requires HYDRA_POSTGRES_URL"):
        open_outbox_store("postgres", tmp_path / "o.db", "")
    with pytest.raises(ValueError, match="unknown"):
        open_outbox_store("redis", tmp_path / "o.db", "")
