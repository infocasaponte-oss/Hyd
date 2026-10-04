# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from uuid import uuid4

from hydra.runtime.artifacts import ArtifactRecord
from hydra.runtime.code_agent import CodeAgentResult
from hydra.runtime.code_replay import build_code_replay_evidence
from hydra.runtime.workspaces import TaskWorkspace


def test_code_replay_extracts_verification_hashes(tmp_path):
    task_id = uuid4()
    workspace = TaskWorkspace(task_id=task_id, root=tmp_path, source=tmp_path)
    verification = ArtifactRecord(
        task_id=task_id,
        kind="verification-report",
        media_type="application/json",
        sha256="c" * 64,
        metadata={
            "baseline_workspace_sha256": "a" * 64,
            "final_workspace_sha256": "b" * 64,
        },
    )
    result = CodeAgentResult(
        accepted=True,
        answer="ok",
        artifacts=[verification],
        workspace=workspace,
    )

    evidence = build_code_replay_evidence(task_id=task_id, result=result)

    assert evidence.verification_artifact_hash == "c" * 64
    assert evidence.baseline_workspace_sha256 == "a" * 64
    assert evidence.final_workspace_sha256 == "b" * 64
