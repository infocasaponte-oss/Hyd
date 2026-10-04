# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Corpus gates: privacy, rights, quality score and tiers.

    Q = 0.25V + 0.20E + 0.15C + 0.15U + 0.10N + 0.10D + 0.05H
    Q < .60 raw only · .60-.80 candidate (bronze) · .80-.92 curated (silver) · > .92 gold candidate

Hard rule: ``credential_found -> corpus_eligible = false`` even if the task was perfect."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel

from hydra.corpus.records import Classification, CorpusRecord, PrivacyReport, Tier, TrainingStatus
from hydra.policy.kernel import DEFAULT_CONFIDENTIAL_PATTERNS, DEFAULT_SECRET_PATTERNS

SECRET_RE = {k: re.compile(v) for k, v in DEFAULT_SECRET_PATTERNS.items()}
PII_RE = {k: re.compile(v) for k, v in DEFAULT_CONFIDENTIAL_PATTERNS.items() if k != "confidential_marker"}
PERSON_RE = re.compile(r"\b(?:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)\s(?:(?:de|del|la)\s)?[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)?\b")
PERSON_CONTEXT = re.compile(r"(?i)\b(?:sr\.?|sra\.?|señor|señora|mr\.?|mrs\.?|ms\.?|dr\.?|dra\.?|"
                            r"trabaja|works|llamad[oa]|named|cliente|customer|paciente|patient|empleado|employee)\b")


class PrivacyGate:
    """Detect secrets/credentials/PII and REJECT, PSEUDONYMIZE or ALLOW."""

    def __init__(self, pseudonymize_persons: bool = True) -> None:
        self.pseudonymize_persons = pseudonymize_persons

    def scan_text(self, text: str) -> tuple[list[str], bool, bool]:
        findings, cred, pii = [], False, False
        for name, rx in SECRET_RE.items():
            if rx.search(text):
                findings.append(f"secret:{name}")
                cred = True
        for name, rx in PII_RE.items():
            if rx.search(text):
                findings.append(f"pii:{name}")
                pii = True
        if self.pseudonymize_persons and PERSON_CONTEXT.search(text) and PERSON_RE.search(text):
            findings.append("pii:person_name")
            pii = True
        return findings, cred, pii

    def pseudonymize(self, obj: Any, table: dict[str, str]) -> Any:
        if isinstance(obj, str):
            out = obj
            for name, rx in PII_RE.items():
                out = rx.sub(lambda m, n=name: table.setdefault(m.group(0), f"<{n.upper()}_{len(table) + 1}>"), out)
            if self.pseudonymize_persons and PERSON_CONTEXT.search(out):
                out = PERSON_RE.sub(lambda m: table.setdefault(m.group(0), f"<PERSON_{len(table) + 1}>"), out)
            return out
        if isinstance(obj, dict):
            return {k: self.pseudonymize(v, table) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.pseudonymize(v, table) for v in obj]
        return obj

    def apply(self, rec: CorpusRecord) -> CorpusRecord:
        text = rec.text()
        findings, cred, pii = self.scan_text(text)
        report = PrivacyReport(scanned=True, findings=findings, credential_found=cred, pii_found=pii)
        if cred:
            report.action = "REJECT"
        elif pii:
            table: dict[str, str] = {}
            for field in ("input", "output", "content", "state", "action"):
                value = getattr(rec, field)
                if value:
                    setattr(rec, field, self.pseudonymize(value, table))
            report.action, report.pseudonyms = "PSEUDONYMIZE", len(table)
        rec.privacy = report
        return rec


class RightsGate:
    """Explicit rights: ``training_allowed = false`` may still be used operationally, never trained on."""

    TRAINABLE_LICENSES = {"proprietary", "apache-2.0", "mit", "bsd-2-clause", "bsd-3-clause", "cc-by-4.0",
                          "cc0-1.0", "cc-by-sa-4.0", "internal"}

    def evaluate(self, rec: CorpusRecord) -> tuple[bool, str]:
        r = rec.rights
        if not r.training_allowed:
            return False, "training not allowed by rights"
        if (r.license or "unknown").lower() not in self.TRAINABLE_LICENSES:
            return False, f"license '{r.license}' requires review"
        if rec.classification in (Classification.TRADE_SECRET, Classification.RESTRICTED):
            return False, f"classification {rec.classification.value}"
        return True, "ok"


class QualityInputs(BaseModel):
    verification: float = 0.0
    evidence: float = 0.0
    correctness: float = 0.0
    utility: float = 0.5
    novelty: float = 0.5
    diversity: float = 0.5
    human: float = 0.5


def quality_score(q: QualityInputs) -> float:
    return round(0.25 * q.verification + 0.20 * q.evidence + 0.15 * q.correctness + 0.15 * q.utility
                 + 0.10 * q.novelty + 0.10 * q.diversity + 0.05 * q.human, 4)


def tier_for(rec: CorpusRecord) -> Tier:
    q = rec.quality
    proof = rec.metadata.get("deterministic_proof") or rec.metadata.get("human_reviewed")
    if q > 0.92 and proof:
        return Tier.PLATINUM
    if q > 0.92:
        return Tier.GOLD
    if q >= 0.80:
        return Tier.SILVER
    if q >= 0.60:
        return Tier.BRONZE
    return Tier.RAW_ONLY


class GateDecision(BaseModel):
    status: TrainingStatus
    reasons: list[str]


class CorpusCurator:
    """incoming -> QUARANTINE -> privacy -> rights -> quality -> dedupe -> contamination -> CURATED/GOLD."""

    @staticmethod
    def artifact_status(
        *,
        rights_confirmed: bool,
        privacy_reviewed: bool,
        training_allowed: bool,
        rights_evidence: bool,
        privacy_status: str,
    ) -> str:
        """Admission for artifact-backed candidates; full text curation is a separate gate."""
        if privacy_status == "flagged":
            return "blocked"
        if (rights_confirmed and privacy_reviewed and training_allowed
                and rights_evidence and privacy_status == "clear"):
            return "curated"
        return "quarantined"

    def __init__(self, dedup=None, contamination=None, min_verification: float = 0.9,
                 privacy: PrivacyGate | None = None, rights: RightsGate | None = None) -> None:
        self.privacy = privacy or PrivacyGate()
        self.rights = rights or RightsGate()
        self.dedup = dedup
        self.contamination = contamination
        self.min_verification = min_verification

    def curate(self, rec: CorpusRecord) -> GateDecision:
        reasons: list[str] = []
        self.privacy.apply(rec)
        if rec.privacy.action == "REJECT":
            return GateDecision(status=TrainingStatus.BLOCKED, reasons=["credential/secret detected"])
        rec.tier = tier_for(rec)
        if rec.verification < self.min_verification and rec.record_type.value not in ("failure", "contrastive",
                                                                                      "counterfactual"):
            reasons.append(f"verification {rec.verification:.2f} < {self.min_verification}")
        ok, why = self.rights.evaluate(rec)
        if not ok:
            reasons.append(why)
        if self.contamination is not None and self.contamination.contaminated(rec):
            return GateDecision(status=TrainingStatus.BLOCKED, reasons=["overlaps an eval/benchmark set"])
        if self.dedup is not None:
            dup = self.dedup.find_duplicate(rec)
            if dup:
                return GateDecision(status=TrainingStatus.DUPLICATE, reasons=[f"duplicate of {dup}"])
        if rec.privacy.action == "PSEUDONYMIZE" and rec.metadata.get("pii_review", True):
            reasons.append("pseudonymized PII: review recommended")
            if not rec.metadata.get("allow_pseudonymized", True):
                return GateDecision(status=TrainingStatus.REVIEW, reasons=reasons)
        blocking = [r for r in reasons if not r.startswith("pseudonymized")]
        if blocking:
            return GateDecision(status=TrainingStatus.QUARANTINED, reasons=reasons)
        if rec.tier in (Tier.GOLD, Tier.PLATINUM):
            return GateDecision(status=TrainingStatus.GOLD, reasons=reasons)
        if rec.tier == Tier.RAW_ONLY:
            return GateDecision(status=TrainingStatus.QUARANTINED, reasons=[*reasons, "quality below 0.60"])
        return GateDecision(status=TrainingStatus.CURATED, reasons=reasons)


def dumps(rec: CorpusRecord) -> str:
    return json.dumps(rec.model_dump(mode="json"), ensure_ascii=False)
