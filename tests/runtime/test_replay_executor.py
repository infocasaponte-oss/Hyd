# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.artifacts import ArtifactStore
from hydra.runtime.events import JsonlEventStore
from hydra.runtime.provenance import ProvenanceLedger, ProvenanceRecord
from hydra.runtime.replay import ReplayManifest, ReplayStore
from hydra.runtime.replay_executor import AuditReplayExecutor


def test_audit_replay_verifies_manifest_ledgers_and_artifacts(tmp_path):
    task_id = uuid4()
    events = JsonlEventStore(tmp_path / "events.jsonl")
    provenance = ProvenanceLedger(tmp_path / "provenance.jsonl")
    artifacts = ArtifactStore(tmp_path / "artifacts")

    artifact = artifacts.put_text(task_id=task_id, kind="output", text="hello")
    events.append(
        event_type="hydra.task.completed",
        aggregate_id=task_id,
        producer="test",
        trace_id="trace",
    )
    provenance.append(
        ProvenanceRecord(
            task_id=task_id,
            trace_id="trace",
            action="task.completed",
        )
    )
    manifest = ReplayStore(tmp_path / "replay").put(
        ReplayManifest(
            task_id=task_id,
            trace_id="trace",
            hydra_version="0.4.0.dev0",
            artifact_hashes=[artifact.sha256],
        )
    )

    result = AuditReplayExecutor(
        events=events,
        provenance=provenance,
        artifact_root=tmp_path / "artifacts",
    ).audit(manifest)

    assert result.valid is True
    assert result.checked_artifacts == 1


def test_audit_replay_rejects_missing_artifact(tmp_path):
    events = JsonlEventStore(tmp_path / "events.jsonl")
    provenance = ProvenanceLedger(tmp_path / "provenance.jsonl")
    task_id = uuid4()
    events.append(
        event_type="hydra.test",
        aggregate_id=task_id,
        producer="test",
        trace_id="trace",
    )
    provenance.append(
        ProvenanceRecord(task_id=task_id, trace_id="trace", action="test")
    )
    manifest = ReplayStore(tmp_path / "replay").put(
        ReplayManifest(
            task_id=task_id,
            trace_id="trace",
            hydra_version="0.4.0.dev0",
            artifact_hashes=["a" * 64],
        )
    )

    result = AuditReplayExecutor(
        events=events,
        provenance=provenance,
        artifact_root=tmp_path / "artifacts",
    ).audit(manifest)

    assert result.valid is False
    assert "artifact missing" in (result.error or "")
