# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Replay evidence of a code-agent run (workspace hashes and artifacts)."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from hydra.artifacts.task_store import ArtifactRecord
from hydra.coding.agent import CodeAgentResult


@dataclass(frozen=True)
class CodeReplayEvidence:
    task_id: UUID
    accepted: bool
    artifact_ids: tuple[str, ...]
    artifact_hashes: tuple[str, ...]
    verification_artifact_hash: str | None
    baseline_workspace_sha256: str | None
    final_workspace_sha256: str | None


def build_code_replay_evidence(
    *,
    task_id: UUID,
    result: CodeAgentResult,
) -> CodeReplayEvidence:
    verification_artifact: ArtifactRecord | None = next(
        (
            artifact
            for artifact in result.artifacts
            if artifact.kind == "verification-report"
        ),
        None,
    )
    baseline_hash = None
    final_hash = None
    if verification_artifact is not None:
        baseline_hash = verification_artifact.metadata.get(
            "baseline_workspace_sha256"
        )
        final_hash = verification_artifact.metadata.get("final_workspace_sha256")

    return CodeReplayEvidence(
        task_id=task_id,
        accepted=result.accepted,
        artifact_ids=tuple(str(item.artifact_id) for item in result.artifacts),
        artifact_hashes=tuple(item.sha256 for item in result.artifacts),
        verification_artifact_hash=(
            verification_artifact.sha256
            if verification_artifact is not None
            else None
        ),
        baseline_workspace_sha256=baseline_hash,
        final_workspace_sha256=final_hash,
    )
