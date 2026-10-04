# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from hydra.artifacts.task_store import ArtifactRecord


def verified_patch_quality(artifacts: list[ArtifactRecord]) -> str:
    by_kind = {artifact.kind: artifact for artifact in artifacts}
    required = {
        "verified-patch",
        "verification-report",
        "tests-before",
        "tests-after",
        "syntax-check",
    }
    report = by_kind.get("verification-report")
    if (
        required.issubset(by_kind)
        and report is not None
        and report.metadata.get("verified") is True
    ):
        return "silver"
    return "bronze"
