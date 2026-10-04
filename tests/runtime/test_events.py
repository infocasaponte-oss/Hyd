# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.events import JsonlEventStore, canonical_hash


def test_event_store_roundtrip(tmp_path):
    store = JsonlEventStore(tmp_path / "events.jsonl")
    task_id = uuid4()
    event = store.append(
        event_type="hydra.task.created",
        aggregate_id=task_id,
        producer="test",
        trace_id="trace",
        payload={"hello": "world"},
    )
    assert event.payload_hash == canonical_hash({"hello": "world"})
    assert store.for_aggregate(task_id)[0].event_id == event.event_id
