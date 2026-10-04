# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.corpus import CorpusGate, CorpusIndex, CorpusRecord


def test_exact_duplicate_is_rejected():
    gate = CorpusGate()
    index = CorpusIndex()
    record = gate.evaluate(
        CorpusRecord(task_id=uuid4(), belief_id=uuid4(), artifact_hashes=["same"])
    )
    duplicate = gate.evaluate(
        CorpusRecord(
            task_id=record.task_id,
            belief_id=record.belief_id,
            artifact_hashes=["same"],
        )
    )
    assert index.accept(record) is True
    assert index.accept(duplicate) is False
