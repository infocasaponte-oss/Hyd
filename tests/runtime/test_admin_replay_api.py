# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from fastapi.testclient import TestClient

from hydra.runtime import api
from hydra.runtime.artifacts import ArtifactStore
from hydra.runtime.events import JsonlEventStore
from hydra.runtime.provenance import ProvenanceLedger, ProvenanceRecord
from hydra.runtime.replay import ReplayManifest, ReplayStore
from hydra.runtime.security import SecurityConfig


def test_admin_replay_audit_validates_real_artifact(tmp_path):
    original_security = api.security_config
    original_replay_store = api.replay_store
    original_artifacts = api.artifacts
    original_events = api.kernel.events
    original_provenance = api.provenance

    api.security_config = SecurityConfig(api_token=None, admin_token="admin-secret")
    api.replay_store = ReplayStore(tmp_path / "replay")
    api.artifacts = ArtifactStore(tmp_path / "artifacts")
    api.kernel.events = JsonlEventStore(tmp_path / "events.jsonl")
    api.provenance = ProvenanceLedger(tmp_path / "provenance.jsonl")

    task_id = uuid4()
    artifact = api.artifacts.put_text(
        task_id=task_id,
        kind="output",
        text="hello",
    )
    api.kernel.events.append(
        event_type="hydra.task.completed",
        aggregate_id=task_id,
        producer="test",
        trace_id="trace",
    )
    api.provenance.append(
        ProvenanceRecord(
            task_id=task_id,
            trace_id="trace",
            action="task.completed",
        )
    )
    api.replay_store.put(
        ReplayManifest(
            task_id=task_id,
            trace_id="trace",
            hydra_version="0.4.0.dev0",
            artifact_hashes=[artifact.sha256],
        )
    )

    try:
        with TestClient(api.app) as client:
            response = client.get(
                f"/hydra/v1/admin/replay/{task_id}/audit",
                headers={"Authorization": "Bearer admin-secret"},
            )
    finally:
        api.security_config = original_security
        api.replay_store = original_replay_store
        api.artifacts = original_artifacts
        api.kernel.events = original_events
        api.provenance = original_provenance

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["checked_artifacts"] == 1


def test_admin_replay_audit_returns_404_for_unknown_task(tmp_path):
    original_security = api.security_config
    original_replay_store = api.replay_store
    api.security_config = SecurityConfig(api_token=None, admin_token="admin-secret")
    api.replay_store = ReplayStore(tmp_path / "replay")

    try:
        with TestClient(api.app) as client:
            response = client.get(
                f"/hydra/v1/admin/replay/{uuid4()}/audit",
                headers={"Authorization": "Bearer admin-secret"},
            )
    finally:
        api.security_config = original_security
        api.replay_store = original_replay_store

    assert response.status_code == 404
