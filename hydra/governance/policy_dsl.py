# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA Policy DSL: declarative, versioned, auditable governance rules.

    rules:
      - id: block-cloud-for-trade-secret
        when: {classification: TRADE_SECRET, target_runtime: CLOUD}
        effect: deny
      - id: allow-python-sandbox
        when: {tool: python.execute, sandboxed: true, network: false}
        effect: allow
      - id: require-review-for-public-release
        when: {artifact_has_ip_candidate: true, target: PUBLIC}
        effect: review

Conditions: exact values, lists (any-of), {"in": [...]}, {"not": v}, {"gte": n}, {"lte": n},
{"glob": "pattern"}. Evaluation: first matching ``deny`` wins, then ``review``, then ``allow``;
no match -> ``default``."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from hydra.core.hashing import hash_obj

EFFECT_ORDER = {"deny": 0, "review": 1, "allow": 2}


class PolicyRule(BaseModel):
    id: str
    when: dict[str, Any] = Field(default_factory=dict)
    effect: str = "allow"
    reason: str = ""
    priority: int = 0


class PolicyVerdict(BaseModel):
    effect: str
    matched: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    policy_version: str = ""


def _match(cond: Any, value: Any) -> bool:
    if isinstance(cond, dict):
        for op, arg in cond.items():
            if op == "in" and value not in arg:
                return False
            if op == "not" and value == arg:
                return False
            if op == "gte" and (value is None or value < arg):
                return False
            if op == "lte" and (value is None or value > arg):
                return False
            if op == "glob" and (value is None or not fnmatch.fnmatchcase(str(value), arg)):
                return False
            if op == "exists" and (value is not None) != bool(arg):
                return False
        return True
    if isinstance(cond, list):
        return value in cond
    if isinstance(cond, str) and isinstance(value, str):
        return cond.upper() == value.upper() if cond.isupper() or value.isupper() else cond == value
    return cond == value


class PolicyEngine:
    def __init__(self, rules: list[PolicyRule] | None = None, default: str = "allow") -> None:
        self.rules = sorted(rules or [], key=lambda r: -r.priority)
        self.default = default
        self.version = hash_obj([r.model_dump() for r in self.rules])[:12]

    @classmethod
    def from_yaml(cls, path: Path) -> PolicyEngine:
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls([PolicyRule(**r) for r in data.get("rules", [])], data.get("default", "allow"))

    def evaluate(self, facts: dict[str, Any]) -> PolicyVerdict:
        matched = [r for r in self.rules if all(_match(c, facts.get(k)) for k, c in r.when.items())]
        if not matched:
            return PolicyVerdict(effect=self.default, policy_version=self.version)
        best = min(matched, key=lambda r: EFFECT_ORDER.get(r.effect, 2))
        return PolicyVerdict(effect=best.effect, matched=[r.id for r in matched],
                             reasons=[r.reason or r.id for r in matched if r.effect == best.effect],
                             policy_version=self.version)
