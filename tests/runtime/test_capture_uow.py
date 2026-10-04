# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.capture_uow import CaptureUnitOfWork, TaskCommit


def test_terminal_commit_is_atomic_with_outbox(tmp_path):
    uow = CaptureUnitOfWork(tmp_path / "hydra.db")
    task_id = uuid4()
    commit = TaskCommit(
        task_id=task_id,
        trace_id="trace",
        status="completed",
        result={"answer": "ok"},
    )
    uow.commit_terminal(
        commit,
        event_payload={
            "event_type": "hydra.task.completed",
            "payload": {"confidence": 0.9},
        },
        provenance_payload={
            "action": "task.completed",
            "outputs": {"answer_sha256": "a" * 64},
        },
        corpus_payload={"record_id": "candidate"},
    )
    restored = uow.get_task_commit(task_id)
    assert restored is not None
    assert restored.status == "completed"
    topics = [message.topic for message in uow.outbox.pending()]
    assert topics == ["event", "provenance", "corpus"]
