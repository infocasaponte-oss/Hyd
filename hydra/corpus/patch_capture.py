# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Learning capture of a verified patch: a task belief with its artifacts as evidence, and a corpus
candidate gated on rights, privacy and patch quality."""
from __future__ import annotations

from uuid import UUID

from hydra.artifacts.task_store import ArtifactRecord, ArtifactStore
from hydra.world.task_beliefs import Belief, BeliefStatus, BeliefStore, EvidenceRef
from hydra.corpus.artifact_candidates import (
    CorpusGate,
    CorpusRecord,
    CorpusStore,
    QualityTier,
    RightsDeclaration,
)
from hydra.corpus.patch_quality import verified_patch_quality
from hydra.corpus.artifact_privacy import PrivacyScanner, PrivacyScanResult


class LearningCapture:
    def __init__(
        self,
        beliefs: BeliefStore | None = None,
        corpus: CorpusStore | None = None,
        gate: CorpusGate | None = None,
        artifacts_store: ArtifactStore | None = None,
        privacy_scanner: PrivacyScanner | None = None,
    ):
        self.beliefs = beliefs or BeliefStore()
        self.corpus = corpus or CorpusStore()
        self.gate = gate or CorpusGate()
        self.artifacts_store = artifacts_store
        self.privacy_scanner = privacy_scanner or PrivacyScanner()

    def capture_verified_patch(
        self,
        *,
        task_id: UUID,
        artifacts: list[ArtifactRecord],
        rights: RightsDeclaration | None = None,
    ) -> tuple[Belief, CorpusRecord]:
        evidence = [
            EvidenceRef(artifact_id=a.artifact_id, sha256=a.sha256, kind=a.kind)
            for a in artifacts
        ]
        belief = self.beliefs.append(
            Belief(
                task_id=task_id,
                claim="Candidate patch passed the configured HYDRA verification policy.",
                status=BeliefStatus.VERIFIED,
                evidence=evidence,
                verifier="hydra.code.verification.v2",
            )
        )
        privacy_scan = PrivacyScanResult()
        if self.artifacts_store is not None:
            privacy_scan = self.privacy_scanner.scan(
                artifacts,
                self.artifacts_store,
            )
        record = CorpusRecord(
            task_id=task_id,
            belief_id=belief.belief_id,
            artifact_hashes=[a.sha256 for a in artifacts],
            quality_tier=QualityTier(verified_patch_quality(artifacts)),
            rights=rights or RightsDeclaration(),
            privacy_scan=privacy_scan,
        )
        return belief, self.corpus.append(self.gate.evaluate(record))
