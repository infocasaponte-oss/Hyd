# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Policy Kernel: structural limits that hold even if a model misbehaves.

- what the system may do at all (forbidden operations),
- which data may leave local infrastructure (sensitivity classification),
- which models may see which data (model clearance),
- which actions require explicit human confirmation.
"""

from __future__ import annotations

import re
from enum import IntEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from hydra.core.contracts import HydraRequest


class Sensitivity(IntEnum):
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    SECRET = 3

    @classmethod
    def parse(cls, value: str | int) -> Sensitivity:
        return cls(value) if isinstance(value, int) else cls[value.upper()]


DEFAULT_SECRET_PATTERNS = {
    "private_key": r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----",
    "api_key": r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}\b|\bAKIA[0-9A-Z]{16}\b|\bghp_[A-Za-z0-9]{30,}\b|\bxox[bap]-[A-Za-z0-9\-]{10,}\b",
    "password_assignment": r"(?i)\b(?:password|passwd|contraseña|pwd)\s*[:=]\s*\S{4,}",
    "secret_assignment": (r"(?i)\b(?:api[_-]?key|secret|access[_-]?token|auth[_-]?token)"
                          r"\s*[:=]\s*['\"]?[^\s'\"]{6,}"),
    "connection_string": r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s:/]+:[^\s@]+@",
    "jwt": r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b",
}

DEFAULT_CONFIDENTIAL_PATTERNS = {
    "credit_card": r"\b(?:\d[ -]?){13,19}\b",
    "iban": r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}\b",
    "spanish_id": r"\b\d{8}[A-HJ-NP-TV-Z]\b|\b[XYZ]\d{7}[A-HJ-NP-TV-Z]\b",
    "email": r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
    "phone": r"(?<!\d)(?:\+\d{1,3}[ ]?)?(?:\d[ ]?){9,12}(?!\d)",
    "confidential_marker": r"(?i)\b(?:confidencial|confidential|interno|internal only|no distribuir|do not distribute)\b",
}

DEFAULT_FORBIDDEN = {
    "mass_destruction": r"(?i)\b(?:bioweapon|arma biológica|nerve agent|agente nervioso|enriquecer uranio|enrich uranium)\b",
    "malware_creation": r"(?i)\b(?:ransomware|keylogger|rootkit|botnet|stealer)\b.*\b(?:crea|create|write|escribe|build|"
                        r"construye|programa|desarrolla|code)\b|\b(?:crea|create|write|escribe|build|construye|programa|"
                        r"desarrolla|code)\b.*\b(?:ransomware|keylogger|rootkit|botnet|stealer)\b",
}


class PolicyRules(BaseModel):
    secret_patterns: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_SECRET_PATTERNS))
    confidential_patterns: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_CONFIDENTIAL_PATTERNS))
    forbidden_request_patterns: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_FORBIDDEN))

    forbidden_tools: set[str] = Field(default_factory=set)
    confirm_tools: set[str] = Field(default_factory=lambda: {"git.apply_patch"})
    confirm_risk_level: int = 4
    confirm_writes: bool = False

    local_only_at: Sensitivity = Sensitivity.CONFIDENTIAL
    """Data at or above this level never leaves local infrastructure."""

    cloud_clearance: Sensitivity = Sensitivity.INTERNAL
    local_clearance: Sensitivity = Sensitivity.SECRET
    model_clearance: dict[str, Sensitivity] = Field(default_factory=dict)
    """Per-model override of the maximum sensitivity it may see."""

    redact_for_logs: bool = True


class Finding(BaseModel):
    kind: str
    level: Sensitivity
    span: tuple[int, int]


class RequestPolicy(BaseModel):
    allowed: bool
    reason: str = ""
    sensitivity: Sensitivity = Sensitivity.PUBLIC
    local_only: bool = False
    findings: list[str] = Field(default_factory=list)


class ToolPolicy(BaseModel):
    allowed: bool
    needs_confirmation: bool = False
    reason: str = ""


class PolicyKernel:
    def __init__(self, rules: PolicyRules | None = None) -> None:
        self.rules = rules or PolicyRules()
        self._secret = {k: re.compile(v) for k, v in self.rules.secret_patterns.items()}
        self._conf = {k: re.compile(v) for k, v in self.rules.confidential_patterns.items()}
        self._forbidden = {k: re.compile(v, re.S) for k, v in self.rules.forbidden_request_patterns.items()}

    @classmethod
    def from_yaml(cls, path: Path | str) -> PolicyKernel:
        p = Path(path)
        if not p.exists():
            return cls()
        data: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        base = PolicyRules()
        for key in ("secret_patterns", "confidential_patterns", "forbidden_request_patterns"):
            if key in data:
                data[key] = {**getattr(base, key), **(data[key] or {})}
        for key in ("local_only_at", "cloud_clearance", "local_clearance"):
            if key in data:
                data[key] = Sensitivity.parse(data[key])
        if "model_clearance" in data:
            data["model_clearance"] = {k: Sensitivity.parse(v) for k, v in data["model_clearance"].items()}
        return cls(PolicyRules.model_validate(data))

    # ------------------------------------------------------------------ data
    def scan(self, text: str) -> list[Finding]:
        findings = []
        for kind, rx in self._secret.items():
            findings += [Finding(kind=kind, level=Sensitivity.SECRET, span=m.span()) for m in rx.finditer(text)]
        for kind, rx in self._conf.items():
            findings += [Finding(kind=kind, level=Sensitivity.CONFIDENTIAL, span=m.span()) for m in rx.finditer(text)]
        return findings

    def classify(self, text: str) -> tuple[Sensitivity, list[Finding]]:
        findings = self.scan(text)
        level = max((f.level for f in findings), default=Sensitivity.PUBLIC)
        return level, findings

    def redact(self, text: str) -> str:
        """Mask secrets and confidential data (used before logging / external storage)."""
        spans = sorted({f.span for f in self.scan(text)}, reverse=True)
        for start, end in spans:
            text = text[:start] + "[REDACTED]" + text[end:]
        return text

    def check_request(self, request: HydraRequest) -> RequestPolicy:
        text = request.text
        for kind, rx in self._forbidden.items():
            if rx.search(text):
                return RequestPolicy(allowed=False, reason=f"forbidden operation: {kind}",
                                     sensitivity=Sensitivity.PUBLIC)
        level, findings = self.classify(text)
        declared = request.metadata.get("sensitivity")
        if declared:
            level = max(level, Sensitivity.parse(declared))
        return RequestPolicy(
            allowed=True,
            sensitivity=level,
            local_only=request.private or level >= self.rules.local_only_at,
            findings=sorted({f.kind for f in findings}),
        )

    # ------------------------------------------------------------------ models
    def clearance(self, model_id: str, local: bool) -> Sensitivity:
        if model_id in self.rules.model_clearance:
            return self.rules.model_clearance[model_id]
        return self.rules.local_clearance if local else self.rules.cloud_clearance

    def model_allowed(self, model_id: str, local: bool, sensitivity: Sensitivity) -> bool:
        return self.clearance(model_id, local) >= sensitivity

    # ------------------------------------------------------------------ tools
    def check_tool(self, name: str, risk_level: int, writes: bool, approved: set[str]) -> ToolPolicy:
        if name in self.rules.forbidden_tools:
            return ToolPolicy(allowed=False, reason=f"tool '{name}' is forbidden by policy")
        needs = (
            name in self.rules.confirm_tools
            or risk_level >= self.rules.confirm_risk_level
            or (self.rules.confirm_writes and writes)
        )
        if needs and name not in approved:
            return ToolPolicy(allowed=False, needs_confirmation=True,
                              reason=f"'{name}' requires explicit confirmation (add it to approved_actions)")
        return ToolPolicy(allowed=True)
