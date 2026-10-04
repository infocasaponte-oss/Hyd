# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Corpus Engine data model: one universal, canonical, immutable envelope.

    Working Memory   -> to solve now
    Long-term Memory -> to solve better later
    Training Corpus  -> to build better intelligences later     (never mixed)

Memoria != corpus: a record only becomes trainable after the privacy, rights, quality,
deduplication and contamination gates."""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from hydra.core.hashing import now_iso


class RecordType(str, Enum):
    SFT = "sft"
    ANSWER = "answer"
    ROUTING_DECISION = "routing_decision"
    TOOL_USE = "tool_use"
    CODE_DEBUG = "code_debug"
    CRITIC = "critic"
    PREFERENCE = "preference"
    PLAN = "plan"
    ACTION = "action"
    STATE_TRANSITION = "state_transition"
    ACTION_VALUE = "action_value"
    PROCEDURE = "procedure"
    EXPERIMENT = "experiment"
    COUNTERFACTUAL = "counterfactual"
    FAILURE = "failure"
    CONTRASTIVE = "contrastive"
    PROCESS_SUPERVISION = "process_supervision"
    VISION = "vision"
    VIDEO = "video"
    REASONING = "reasoning"
    TRANSLATION = "translation"
    ENTITY_RESOLUTION = "entity_resolution"
    RELATION_EXTRACTION = "relation_extraction"
    CAUSAL = "causal"
    ARTIFACT = "artifact"


class TrainingStatus(str, Enum):
    RAW = "RAW"
    QUARANTINED = "QUARANTINED"
    CURATED = "CURATED"
    GOLD = "GOLD"
    BLOCKED = "BLOCKED"
    DUPLICATE = "DUPLICATE"
    REVIEW = "REVIEW"
    TOMBSTONED = "TOMBSTONED"


class Tier(str, Enum):
    RAW_ONLY = "raw_only"
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class Classification(str, Enum):
    PUBLIC = "PUBLIC"
    LICENSED = "LICENSED"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    TRADE_SECRET = "TRADE_SECRET"
    RESTRICTED = "RESTRICTED"


class RightsMetadata(BaseModel):
    owner: str | None = "Luis Manuel Cousido Hermida"
    license: str | None = "proprietary"
    training_allowed: bool = False
    redistribution_allowed: bool = False
    commercial_allowed: bool | None = True
    allow_internal_knowledge: bool = True
    cloud_allowed: bool = False
    source_url: str | None = None
    restrictions: list[str] = Field(default_factory=list)


class PrivacyReport(BaseModel):
    scanned: bool = False
    findings: list[str] = Field(default_factory=list)
    credential_found: bool = False
    pii_found: bool = False
    action: str = "ALLOW"  # ALLOW | REDACT | PSEUDONYMIZE | REJECT | REVIEW
    pseudonyms: int = 0


class CorpusRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    record_type: RecordType
    created_at: str = Field(default_factory=now_iso)
    source_type: str = "hydra_execution"
    source_id: str | None = None
    source_task_id: str | None = None
    language: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    output: dict[str, Any] = Field(default_factory=dict)
    content: dict[str, Any] = Field(default_factory=dict)
    reward: float | None = None
    quality: float = 0.0
    verification: float = 0.0
    difficulty: float | None = None
    domain: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    synthetic: bool = False
    synthetic_generation: int = 0
    classification: Classification = Classification.INTERNAL
    tenant_id: str | None = None
    residency: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    rights: RightsMetadata = Field(default_factory=RightsMetadata)
    privacy: PrivacyReport = Field(default_factory=PrivacyReport)
    hashes: dict[str, str] = Field(default_factory=dict)
    tier: Tier = Tier.RAW_ONLY
    training_status: TrainingStatus = TrainingStatus.RAW
    flags: list[str] = Field(default_factory=list)
    """hard | frontier | adversarial | temporal_holdout | contrastive ..."""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def trainable(self) -> bool:
        return self.training_status in (TrainingStatus.CURATED, TrainingStatus.GOLD) and self.rights.training_allowed

    def text(self) -> str:
        """Flat text used for dedup/contamination/search."""
        parts = []
        for block in (self.input, self.output, self.content, self.action or {}, self.state or {}):
            for v in block.values():
                parts.append(v if isinstance(v, str) else str(v))
        return "\n".join(parts)


class LineageEdge(BaseModel):
    parent_id: str
    child_id: str
    transformation: str
    pipeline_version: str = "hydra-corpus/1"
    created_at: str = Field(default_factory=now_iso)


class Tombstone(BaseModel):
    record_id: str
    reason: str
    timestamp: str = Field(default_factory=now_iso)
    affected_datasets: list[str] = Field(default_factory=list)
    affected_models: list[str] = Field(default_factory=list)
    affected_artifacts: list[str] = Field(default_factory=list)
