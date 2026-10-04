# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""License Ledger and License Compatibility Engine.

Code licenses never implicitly cover weights or data: every component (code, model,
weights, dataset, tokenizer, LoRA, container, package) carries its own record, and the
machine-readable policy decides ALLOW / REVIEW_REQUIRED / DENY per target profile."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class LicenseClass(str, Enum):
    PERMISSIVE = "permissive"
    WEAK_COPYLEFT = "weak-copyleft"
    COPYLEFT = "copyleft"
    NETWORK_COPYLEFT = "network-copyleft"
    NON_COMMERCIAL = "non-commercial"
    RESEARCH_ONLY = "research-only"
    OPEN_WEIGHTS_RESTRICTED = "open-weights-restricted"
    PROPRIETARY_INTERNAL = "proprietary-internal"
    COMMERCIAL_APPROVED = "commercial-approved"
    CUSTOM = "custom-license"
    UNKNOWN = "unknown"


class DistributionLabel(str, Enum):
    OPEN_SOURCE_SOFTWARE = "OPEN_SOURCE_SOFTWARE"
    OPEN_SOURCE_AI = "OPEN_SOURCE_AI"
    OPEN_WEIGHTS = "OPEN_WEIGHTS"
    SOURCE_AVAILABLE = "SOURCE_AVAILABLE"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    COMMERCIAL_LICENSE = "COMMERCIAL_LICENSE"
    PROPRIETARY = "PROPRIETARY"
    INTERNAL_ONLY = "INTERNAL_ONLY"


SPDX_CLASSES: dict[str, LicenseClass] = {
    **{k: LicenseClass.PERMISSIVE for k in ("mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "zlib",
                                           "psf-2.0", "python-2.0", "unlicense", "cc0-1.0", "cc-by-4.0", "0bsd",
                                           "mit-0", "hpnd", "bsl-1.0", "upl-1.0", "postgresql")},
    **{k: LicenseClass.WEAK_COPYLEFT for k in ("lgpl-2.1", "lgpl-3.0", "mpl-2.0", "epl-2.0", "cddl-1.0")},
    **{k: LicenseClass.COPYLEFT for k in ("gpl-2.0", "gpl-3.0", "cc-by-sa-4.0")},
    **{k: LicenseClass.NETWORK_COPYLEFT for k in ("agpl-3.0", "sspl-1.0")},
    **{k: LicenseClass.NON_COMMERCIAL for k in ("cc-by-nc-4.0", "cc-by-nc-sa-4.0", "cc-by-nc-nd-4.0")},
    **{k: LicenseClass.OPEN_WEIGHTS_RESTRICTED for k in ("llama2", "llama3", "llama3.1", "llama3.2", "llama3.3",
                                                         "gemma", "qwen", "openrail", "openrail-m", "bigscience-openrail-m",
                                                         "creativeml-openrail-m", "deepseek")},
    "research-only": LicenseClass.RESEARCH_ONLY,
    "proprietary": LicenseClass.PROPRIETARY_INTERNAL,
    "internal": LicenseClass.PROPRIETARY_INTERNAL,
    "commercial": LicenseClass.COMMERCIAL_APPROVED,
}
ALIASES = {"apache 2.0": "apache-2.0", "apache license 2.0": "apache-2.0", "apache software license": "apache-2.0",
           "mit license": "mit", "bsd license": "bsd-3-clause", "bsd": "bsd-3-clause", "new bsd": "bsd-3-clause",
           "gnu general public license v3 (gplv3)": "gpl-3.0", "gplv3": "gpl-3.0", "gplv2": "gpl-2.0",
           "mozilla public license 2.0 (mpl 2.0)": "mpl-2.0", "python software foundation license": "psf-2.0",
           "isc license (iscl)": "isc", "the unlicense (unlicense)": "unlicense"}


def classify(license_id: str | None) -> LicenseClass:
    if not license_id:
        return LicenseClass.UNKNOWN
    key = ALIASES.get(license_id.strip().lower(), license_id.strip().lower())
    if key in SPDX_CLASSES:
        return SPDX_CLASSES[key]
    for k, v in SPDX_CLASSES.items():
        if key.startswith(k):
            return v
    return LicenseClass.CUSTOM if key not in ("unknown", "none", "") else LicenseClass.UNKNOWN


class LicenseRecord(BaseModel):
    artifact_id: str
    artifact_type: str
    """source_code | model | weights | dataset | tokenizer | lora | container | python_package | paper"""
    origin: str = ""
    license_id: str | None = None
    copyright_holders: list[str] = Field(default_factory=list)
    commercial_use: bool | None = None
    redistribution: bool | None = None
    derivatives: bool | None = None
    training_use: bool | None = None
    attribution_required: bool = False
    restrictions: list[str] = Field(default_factory=list)
    license_text_hash: str | None = None

    @property
    def license_class(self) -> LicenseClass:
        return classify(self.license_id)


class LicenseProfile(BaseModel):
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)
    require_review: list[str] = Field(default_factory=list)


DEFAULT_PROFILES: dict[str, LicenseProfile] = {
    "enterprise-commercial": LicenseProfile(
        allow=["permissive", "proprietary-internal", "commercial-approved", "weak-copyleft"],
        deny=["research-only", "non-commercial", "unknown", "network-copyleft"],
        require_review=["custom-license", "copyleft", "open-weights-restricted"]),
    "internal": LicenseProfile(
        allow=["permissive", "proprietary-internal", "commercial-approved", "weak-copyleft", "copyleft",
               "open-weights-restricted", "research-only", "non-commercial"],
        deny=[], require_review=["unknown", "custom-license", "network-copyleft"]),
    "open-release": LicenseProfile(
        allow=["permissive"], deny=["proprietary-internal", "research-only", "non-commercial", "unknown"],
        require_review=["copyleft", "weak-copyleft", "open-weights-restricted", "custom-license",
                        "commercial-approved", "network-copyleft"]),
    "commercial_distribution": LicenseProfile(
        allow=["permissive", "proprietary-internal", "commercial-approved"],
        deny=["research-only", "non-commercial", "unknown"],
        require_review=["custom-license", "copyleft", "weak-copyleft", "open-weights-restricted", "network-copyleft"]),
}


class LicenseIssue(BaseModel):
    component: str
    license: str | None
    license_class: str
    reason: str
    severity: str  # deny | review


class LicenseReport(BaseModel):
    target: str
    status: str  # ALLOW | REVIEW_REQUIRED | DENY
    issues: list[LicenseIssue] = Field(default_factory=list)
    components: int = 0
    classes: dict[str, int] = Field(default_factory=dict)


class LicenseEngine:
    def __init__(self, profiles: dict[str, LicenseProfile] | None = None) -> None:
        self.profiles = dict(DEFAULT_PROFILES)
        self.profiles.update(profiles or {})
        self.records: dict[str, LicenseRecord] = {}
        self.exceptions: dict[tuple[str, str], str] = {}

    @classmethod
    def from_yaml(cls, path: Path) -> LicenseEngine:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        profiles = {k: LicenseProfile(**v) for k, v in (data.get("profiles") or {}).items()}
        eng = cls(profiles)
        for r in data.get("components") or []:
            eng.register(LicenseRecord(**r))
        return eng

    def register(self, rec: LicenseRecord) -> LicenseRecord:
        self.records[rec.artifact_id] = rec
        return rec

    def grant_exception(self, component: str, target: str, approver: str) -> None:
        self.exceptions[(component, target)] = approver

    def evaluate(self, target: str, components: list[LicenseRecord | str]) -> LicenseReport:
        profile = self.profiles.get(target) or self.profiles["enterprise-commercial"]
        issues, classes = [], {}
        recs = [c if isinstance(c, LicenseRecord) else self.records.get(c) or
                LicenseRecord(artifact_id=c, artifact_type="unknown") for c in components]
        for r in recs:
            cls = r.license_class.value
            classes[cls] = classes.get(cls, 0) + 1
            if (r.artifact_id, target) in self.exceptions:
                continue
            if cls in profile.deny:
                issues.append(LicenseIssue(component=r.artifact_id, license=r.license_id, license_class=cls,
                                           reason=f"class {cls} denied for {target}", severity="deny"))
            elif cls in profile.require_review or cls not in profile.allow:
                issues.append(LicenseIssue(component=r.artifact_id, license=r.license_id, license_class=cls,
                                           reason=f"class {cls} requires review for {target}", severity="review"))
            if target != "internal" and r.artifact_type in ("dataset", "weights", "model") and r.training_use is False:
                issues.append(LicenseIssue(component=r.artifact_id, license=r.license_id, license_class=cls,
                                           reason="training use not granted", severity="review"))
            if target in ("open-release", "commercial_distribution") and r.redistribution is False:
                issues.append(LicenseIssue(component=r.artifact_id, license=r.license_id, license_class=cls,
                                           reason="redistribution unclear/forbidden", severity="deny"))
        status = ("DENY" if any(i.severity == "deny" for i in issues) else
                  "REVIEW_REQUIRED" if issues else "ALLOW")
        return LicenseReport(target=target, status=status, issues=issues, components=len(recs), classes=classes)

    @staticmethod
    def label(components: list[LicenseRecord]) -> DistributionLabel:
        classes = {c.license_class for c in components}
        if classes <= {LicenseClass.PERMISSIVE}:
            return DistributionLabel.OPEN_SOURCE_SOFTWARE
        if LicenseClass.PROPRIETARY_INTERNAL in classes:
            return DistributionLabel.PROPRIETARY
        if LicenseClass.RESEARCH_ONLY in classes or LicenseClass.NON_COMMERCIAL in classes:
            return DistributionLabel.RESEARCH_ONLY
        if LicenseClass.OPEN_WEIGHTS_RESTRICTED in classes:
            return DistributionLabel.OPEN_WEIGHTS
        return DistributionLabel.SOURCE_AVAILABLE


def installed_package_licenses() -> list[LicenseRecord]:
    """License records for the Python dependencies actually installed (SBOM input)."""
    from importlib.metadata import distributions

    out = []
    for d in distributions():
        name = d.metadata.get("Name")
        if not name:
            continue
        lic = d.metadata.get("License-Expression") or d.metadata.get("License") or ""
        if not lic or len(lic) > 60:
            classifiers = [c.split("::")[-1].strip() for c in (d.metadata.get_all("Classifier") or [])
                           if c.startswith("License ::")]
            lic = classifiers[0] if classifiers else (lic[:60] if lic else "unknown")
        out.append(LicenseRecord(artifact_id=f"pypi:{name}=={d.version}", artifact_type="python_package",
                                 origin="pypi", license_id=lic, redistribution=None))
    return out


def summary(records: list[LicenseRecord]) -> dict[str, Any]:
    by: dict[str, list[str]] = {}
    for r in records:
        by.setdefault(r.license_class.value, []).append(r.artifact_id)
    return {k: sorted(v) for k, v in sorted(by.items())}
