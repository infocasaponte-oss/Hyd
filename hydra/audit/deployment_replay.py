# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Replay manifest fields taken from the deployment that served a task."""
from __future__ import annotations

from uuid import UUID

from hydra.deploy.deployment import Deployment
from hydra.audit.replay import ReplayManifest


def runtime_replay_manifest(
    *,
    task_id: UUID,
    trace_id: str,
    hydra_version: str,
    deployment: Deployment,
    event_types: list[str],
    event_ids: list[str] | None = None,
) -> ReplayManifest:
    return ReplayManifest(
        task_id=task_id,
        trace_id=trace_id,
        hydra_version=hydra_version,
        model_id=deployment.variant.lineage.base_model,
        selected_variant_id=str(deployment.variant_id),
        selected_variant_sha256=deployment.variant.artifact_sha256,
        deployment_generation=deployment.generation,
        artifact_hashes=[deployment.variant.artifact_sha256],
        event_types=event_types,
        event_ids=event_ids or [],
    )
