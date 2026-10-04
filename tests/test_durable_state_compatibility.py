# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import importlib
from uuid import uuid4

import pytest


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [
        ("hydra.runtime.hash_chain", "hydra.core.hash_chain"),
        ("hydra.runtime.events", "hydra.core.durable_events"),
        ("hydra.runtime.provenance", "hydra.provenance.ledger"),
        ("hydra.runtime.outbox", "hydra.core.outbox"),
        ("hydra.runtime.outbox_metrics", "hydra.core.outbox_metrics"),
        ("hydra.runtime.readiness", "hydra.deploy.readiness"),
    ],
)
def test_legacy_module_is_canonical(legacy, canonical):
    assert importlib.import_module(legacy) is importlib.import_module(canonical)


def test_lock_registry_is_shared_across_import_paths(tmp_path):
    old = importlib.import_module("hydra.runtime.hash_chain")
    new = importlib.import_module("hydra.core.hash_chain")
    assert old.lock_for(tmp_path / "events.jsonl") is new.lock_for(tmp_path / "events.jsonl")


def test_event_chain_reopens_and_deduplicates_across_import_paths(tmp_path):
    old = importlib.import_module("hydra.runtime.events")
    new = importlib.import_module("hydra.core.durable_events")
    path = tmp_path / "events.jsonl"
    kwargs = dict(event_type="test", aggregate_id=uuid4(), producer="test",
                  trace_id="trace", payload={"value": 1}, source_message_id=uuid4())
    first = old.JsonlEventStore(path).append(**kwargs)
    reopened = new.JsonlEventStore(path)
    assert reopened.append(**kwargs).event_id == first.event_id
    second = reopened.append(**{**kwargs, "source_message_id": uuid4()})
    assert second.previous_hash == first.event_hash
    assert old.JsonlEventStore(path).verify_integrity().valid
    assert len(reopened.for_aggregate(kwargs["aggregate_id"])) == 2
