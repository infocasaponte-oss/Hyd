# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

import pytest

from hydra.core import task_commit
from hydra.runtime import capture_uow


def test_legacy_capture_is_shared_implementation():
    assert capture_uow is task_commit


@pytest.mark.parametrize("failure_topic", ["event", "provenance", "corpus"])
def test_failed_enqueue_rolls_back_terminal_result(tmp_path, monkeypatch, failure_topic):
    uow = task_commit.CaptureUnitOfWork(tmp_path / "hydra.db")
    commit = task_commit.TaskCommit(uuid4(), "trace", "completed", {"answer": "ok"})
    enqueue = uow.outbox.enqueue

    def fail(connection, **kwargs):
        if kwargs["topic"] == failure_topic:
            raise RuntimeError("injected queue failure")
        return enqueue(connection, **kwargs)

    monkeypatch.setattr(uow.outbox, "enqueue", fail)
    with pytest.raises(RuntimeError, match="injected queue failure"):
        uow.commit_terminal(
            commit,
            event_payload={"event_type": "completed"},
            provenance_payload={"action": "completed"},
            corpus_payload={"record_id": "candidate"},
        )
    reopened = task_commit.CaptureUnitOfWork(tmp_path / "hydra.db")
    assert reopened.get_task_commit(commit.task_id) is None
    assert reopened.outbox.pending() == []
