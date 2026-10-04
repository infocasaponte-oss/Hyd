# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Beliefs about executed tasks (e.g. "this patch passed the verification policy"), with the artifacts
that back them. Not ``hydra.world.model.Belief`` (the World Model's probabilistic belief): in the gateway
``hydra.world.runtime_beliefs.WorldBeliefStore`` turns each task belief into a World Model observation."""
from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from hydra.core.eventlog import FileLog
from hydra.core.runtime_paths import runtime_path


class BeliefStatus(StrEnum):
    HYPOTHESIS = "hypothesis"
    SUPPORTED = "supported"
    VERIFIED = "verified"
    CONTESTED = "contested"
    REJECTED = "rejected"
    OBSOLETE = "obsolete"


class EvidenceRef(BaseModel):
    artifact_id: UUID
    sha256: str
    kind: str


class Belief(BaseModel):
    belief_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    claim: str
    status: BeliefStatus
    evidence: list[EvidenceRef] = Field(default_factory=list)
    verifier: str


class BeliefStore:
    """Runtime beliefs on a ``hydra.core.eventlog`` log (``beliefs.jsonl`` or the PostgreSQL stream
    ``runtime/beliefs.jsonl``). In the gateway they go to the World Model instead
    (``hydra.world.runtime_beliefs.WorldBeliefStore``)."""

    STREAM = "runtime/beliefs.jsonl"

    def __init__(self, path: str | Path = runtime_path("beliefs.jsonl"), log=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.log = log if log is not None else FileLog(self.path, self.STREAM)

    def append(self, belief: Belief) -> Belief:
        self.log.append(belief.model_dump_json())
        return belief
