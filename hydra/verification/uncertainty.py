# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Uncertainty Router: find *which part* of an answer is uncertain and investigate only that.

    answer
    ├─ claim A -> .98
    ├─ claim B -> .94
    ├─ claim C -> .51   <- investigate
    └─ claim D -> .87
"""

from __future__ import annotations

import re

from hydra.core.contracts import Claim
from hydra.memory.embeddings import tokenize

CODE_BLOCK = re.compile(r"```.*?```", re.S)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡0-9\"'(])|\n+")
NUM = re.compile(r"-?\d+(?:[.,]\d+)?")
STOP = {"el", "la", "los", "las", "un", "una", "de", "del", "en", "y", "o", "que", "es", "se", "por", "con",
        "para", "the", "a", "an", "of", "in", "and", "or", "is", "are", "to", "for", "with", "this", "esto",
        "esta", "este", "it", "be", "as", "on", "al", "lo", "su", "sus", "no", "si"}

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["supported", "refuted", "uncertain"]},
        "correction": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict"],
}


def content_tokens(text: str) -> set[str]:
    return {t for t in tokenize(text) if t not in STOP and len(t) > 1}


def segment_claims(answer: str, max_claims: int = 20) -> list[Claim]:
    claims: list[Claim] = []
    for i, block in enumerate(CODE_BLOCK.findall(answer)):
        claims.append(Claim(id=f"code{i + 1}", text=block[:2000], confidence=0.0))
    prose = CODE_BLOCK.sub(" ", answer)
    for part in SENTENCE.split(prose):
        text = part.strip(" -*•\t")
        if len(text) < 12 or text.endswith("?") or len(content_tokens(text)) < 2:
            continue
        claims.append(Claim(id=f"c{len(claims) + 1}", text=text[:600], confidence=0.0))
        if len(claims) >= max_claims:
            break
    return claims


def containment(claim: str, other: str) -> float:
    ct = content_tokens(claim)
    if not ct:
        return 0.0
    return len(ct & content_tokens(other)) / len(ct)


def assess_claims(
    claims: list[Claim],
    base_confidence: float,
    other_answers: list[str],
    tool_outputs: list[str],
    critic_issues: list[str],
    threshold: float = 0.6,
) -> list[Claim]:
    tool_text = "\n".join(tool_outputs)
    tool_numbers = set(NUM.findall(tool_text))
    for c in claims:
        conf = base_confidence
        if other_answers:
            support = max(containment(c.text, o) for o in other_answers)
            conf = 0.6 * base_confidence + 0.4 * support
        nums = set(NUM.findall(c.text))
        if nums and tool_numbers:
            conf += 0.1 if nums & tool_numbers else -0.15
        for issue in critic_issues:
            if containment(issue, c.text) >= 0.4:
                conf -= 0.3
        c.confidence = round(max(0.0, min(1.0, conf)), 4)
        c.status = "supported" if c.confidence >= threshold else "uncertain"
    return claims


def apply_verdict(claim: Claim, verdict: dict) -> Claim:
    v = verdict.get("verdict", "uncertain")
    if v == "supported":
        claim.confidence = max(claim.confidence, 0.8)
        claim.status = "supported"
    elif v == "refuted":
        claim.confidence = min(claim.confidence, 0.1)
        claim.status = "refuted"
        claim.correction = verdict.get("correction") or None
    else:
        claim.status = "uncertain"
    return claim
