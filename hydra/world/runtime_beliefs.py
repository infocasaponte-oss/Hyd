# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Route HYDRA-SO runtime beliefs (verified patches) into the platform World Model.

The runtime ``BeliefStore`` only appends to ``runtime/beliefs.jsonl``. This store keeps that
file (replay manifests reference it) and also records every belief as an observation in the
World Model, with the patch artifacts as UNIT_TEST evidence, so verified code changes take
part in belief scoring, contradiction handling and the time machine."""

from __future__ import annotations

from hydra.world.task_beliefs import Belief, BeliefStatus, BeliefStore
from hydra.world.model import EvidenceType, Observation

_STRONG = {BeliefStatus.VERIFIED, BeliefStatus.SUPPORTED}


class WorldBeliefStore(BeliefStore):
    def __init__(self, world, path, log=None) -> None:
        """``log``: keep the store's log (the shared ``runtime/beliefs.jsonl`` stream on PostgreSQL);
        without it, the file at ``path``."""
        super().__init__(path, log=log)
        self.world = world

    def append(self, belief: Belief) -> Belief:
        super().append(belief)
        evidence = ",".join(ref.sha256 for ref in belief.evidence) or str(belief.belief_id)
        observation = Observation(
            observer=belief.verifier, statement=belief.claim, subject=f"task:{belief.task_id}",
            predicate="verification", value=belief.status.value, source_ref=evidence,
            source_family=belief.verifier, confidence=0.95 if belief.status in _STRONG else 0.5,
            evidence_type=EvidenceType.UNIT_TEST if belief.status in _STRONG else EvidenceType.MODEL)
        self.world.apply(self.world.observe(observation))
        return belief
