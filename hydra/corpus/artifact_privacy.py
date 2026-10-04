# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
from __future__ import annotations

from hydra.corpus.gates import PrivacyGate
from hydra.corpus.privacy_contracts import PrivacyScanResult, PrivacyScanStatus
from hydra.artifacts.task_store import ArtifactRecord, ArtifactStore


_GATE = PrivacyGate(pseudonymize_persons=False)


def _finding_types(text: str) -> set[str]:
    """Detection is shared with the corpus PrivacyGate; names keep the runtime vocabulary."""
    findings, _, _ = _GATE.scan_text(text)
    types = set()
    for finding in findings:
        kind, name = finding.split(":", 1)
        if kind == "secret":
            types.add("private_key" if name == "private_key" else "credential_or_secret")
        else:
            types.add(name)
    return types


class PrivacyScanner:
    def __init__(
        self,
        *,
        max_artifact_bytes: int = 1 * 1024 * 1024,
        max_total_bytes: int = 4 * 1024 * 1024,
    ):
        self.max_artifact_bytes = max_artifact_bytes
        self.max_total_bytes = max_total_bytes

    def scan(
        self,
        artifacts: list[ArtifactRecord],
        store: ArtifactStore,
    ) -> PrivacyScanResult:
        findings: set[str] = set()
        scanned = 0
        total = 0
        incomplete = False

        text_artifacts = [
            artifact
            for artifact in artifacts
            if artifact.media_type.startswith("text/")
            or "json" in artifact.media_type
        ]
        if not text_artifacts:
            return PrivacyScanResult(status=PrivacyScanStatus.INCOMPLETE)

        for artifact in text_artifacts:
            try:
                data = store.get_bytes(
                    artifact.sha256,
                    max_bytes=self.max_artifact_bytes,
                )
            except (FileNotFoundError, ValueError):
                incomplete = True
                continue

            if total + len(data) > self.max_total_bytes:
                incomplete = True
                break

            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                incomplete = True
                continue

            scanned += 1
            total += len(data)
            findings |= _finding_types(text)

        if findings:
            status = PrivacyScanStatus.FLAGGED
        elif incomplete or scanned != len(text_artifacts):
            status = PrivacyScanStatus.INCOMPLETE
        else:
            status = PrivacyScanStatus.CLEAR

        return PrivacyScanResult(
            status=status,
            finding_types=sorted(findings),
            artifacts_scanned=scanned,
            bytes_scanned=total,
        )

__all__ = ["PrivacyScanStatus", "PrivacyScanResult", "PrivacyScanner"]
