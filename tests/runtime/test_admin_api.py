# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from fastapi.testclient import TestClient

from hydra.runtime import api
from hydra.runtime.capture_uow import CaptureUnitOfWork
from hydra.runtime.security import SecurityConfig


def test_admin_can_list_and_requeue_dead_letter(tmp_path):
    original_security = api.security_config
    original_uow = api.capture_uow
    api.security_config = SecurityConfig(api_token=None, admin_token="admin-secret")
    api.capture_uow = CaptureUnitOfWork(tmp_path / "hydra.db")

    with api.capture_uow.outbox.transaction() as connection:
        message = api.capture_uow.outbox.enqueue(
            connection,
            topic="event",
            aggregate_id=uuid4(),
            trace_id="trace",
            payload={"event_type": "hydra.test", "payload": {"secret": "hidden"}},
        )
    api.capture_uow.outbox.record_failure(
        message.id,
        error="boom",
        next_attempt_at=None,
        dead_letter=True,
    )

    try:
        with TestClient(api.app) as client:
            headers = {"Authorization": "Bearer admin-secret"}
            listed = client.get(
                "/hydra/v1/admin/outbox/dead-letters",
                headers=headers,
            )
            retried = client.post(
                f"/hydra/v1/admin/outbox/dead-letters/{message.id}/retry",
                headers=headers,
            )
    finally:
        api.security_config = original_security
        api.capture_uow = original_uow

    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] == 1
    assert "payload" not in body["messages"][0]
    assert "secret" not in str(body)
    assert retried.status_code == 200
    assert retried.json()["requeued"] is True
