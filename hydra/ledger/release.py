# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Release Engineering and the Release Gate.

    MODEL / DATASET / CODE / PAPER / DOCKER IMAGE / GGUF
      -> SECURITY + LICENSE + IP + PRIVACY + QUALITY  -> signed release manifest

A release is a verifiable object (component versions, SBOM/ML-BOM, licenses, provenance,
eval results, clearances, hashes, Ed25519 signature), not a git tag. Environments are
promoted DEV -> LAB -> STAGING -> CANARY -> PRODUCTION only through gates."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

import hydra
from hydra.core.atomic import write_text_atomic
from hydra.core.hashing import canonical_json, now_iso, sha256_file, sha256_hex
from hydra.ledger.bom import cyclonedx, sbom
from hydra.ledger.chain import Ledger, LedgerEventType
from hydra.ledger.ip import IPRegistry
from hydra.ledger.licenses import LicenseEngine, LicenseRecord, installed_package_licenses
from hydra.ledger.signing import Signer, verify_envelope

ENVIRONMENTS = ["DEV", "LAB", "STAGING", "CANARY", "PRODUCTION"]
SECRET_SCAN = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bsk-[A-Za-z0-9]{20,}|\bghp_[A-Za-z0-9]{30,}"
                         r"|\bAKIA[0-9A-Z]{16}\b")


class CheckResult(BaseModel):
    name: str
    approved: bool
    details: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class ReleaseDecision(BaseModel):
    approved: bool
    target: str
    checks: list[CheckResult]
    blocked_reasons: list[str] = Field(default_factory=list)


class ReleaseArtifact(BaseModel):
    id: str
    kind: str  # model | dataset | code | paper | container | gguf
    path: str | None = None
    invention_refs: list[str] = Field(default_factory=list)
    license_components: list[str] = Field(default_factory=list)
    quality: dict[str, Any] = Field(default_factory=dict)
    """e.g. {"eval_passed": true, "score": 0.93}"""
    privacy_cleared: bool = True
    contains_pii: bool = False


class ReleaseGate:
    def __init__(self, ip: IPRegistry | None, licenses: LicenseEngine, ledger: Ledger | None = None,
                 min_quality: float = 0.8) -> None:
        self.ip = ip
        self.licenses = licenses
        self.ledger = ledger
        self.min_quality = min_quality

    def _ip(self, a: ReleaseArtifact, target: str) -> CheckResult:
        if target not in ("public", "open-release", "commercial_distribution") or self.ip is None:
            return CheckResult(name="ip", approved=True, reason="non-public target")
        ok, blocked = self.ip.disclosure_check(a.invention_refs)
        return CheckResult(name="ip", approved=ok, details={"blocked_inventions": blocked,
                                                            "statuses": {i: self.ip.get(i).status.value for i in blocked}},
                           reason="" if ok else "Unresolved confidential invention: IP approval or filing/"
                                                "disclosure status change required")

    def _license(self, a: ReleaseArtifact, target: str) -> CheckResult:
        profile = {"public": "open-release"}.get(target, target)
        rep = self.licenses.evaluate(profile, a.license_components)
        return CheckResult(name="license", approved=rep.status == "ALLOW", details=rep.model_dump(),
                           reason="" if rep.status == "ALLOW" else rep.status)

    def _privacy(self, a: ReleaseArtifact) -> CheckResult:
        ok = a.privacy_cleared and not a.contains_pii
        return CheckResult(name="privacy", approved=ok, reason="" if ok else "privacy clearance missing / PII present")

    def _security(self, a: ReleaseArtifact) -> CheckResult:
        hits = []
        if a.path and Path(a.path).exists():
            files = [Path(a.path)] if Path(a.path).is_file() else [p for p in Path(a.path).rglob("*") if p.is_file()]
            for p in files[:2000]:
                if p.suffix in (".gguf", ".safetensors", ".bin", ".pt", ".parquet") or p.stat().st_size > 5_000_000:
                    continue
                try:
                    if SECRET_SCAN.search(p.read_text(encoding="utf-8", errors="ignore")):
                        hits.append(str(p))
                except OSError:
                    continue
        return CheckResult(name="security", approved=not hits, details={"secret_hits": hits[:20]},
                           reason="" if not hits else "secrets found in release payload")

    def _quality(self, a: ReleaseArtifact) -> CheckResult:
        if a.kind in ("code", "paper", "container"):
            ok = a.quality.get("tests_passed", True)
        else:
            ok = bool(a.quality.get("eval_passed")) and float(a.quality.get("score", 0)) >= self.min_quality
        return CheckResult(name="quality", approved=ok, details=a.quality, reason="" if ok else "evals not passed")

    def evaluate(self, a: ReleaseArtifact, target: str) -> ReleaseDecision:
        checks = [self._ip(a, target), self._license(a, target), self._privacy(a), self._security(a), self._quality(a)]
        decision = ReleaseDecision(approved=all(c.approved for c in checks), target=target, checks=checks,
                                   blocked_reasons=[f"{c.name}: {c.reason}" for c in checks if not c.approved])
        if self.ledger is not None:
            self.ledger.append(LedgerEventType.RELEASE_APPROVED if decision.approved else LedgerEventType.RELEASE_BLOCKED,
                               {"artifact": a.id, "kind": a.kind, "target": target,
                                "blocked": decision.blocked_reasons}, object_type="release", object_id=a.id)
        return decision


# ------------------------------------------------------------------------------ manifests
class ReleaseManifest(BaseModel):
    release: str
    environment: str = "DEV"
    created_at: str = Field(default_factory=now_iso)
    components: dict[str, str] = Field(default_factory=dict)
    """core / router / planner / world_schema / corpus / policies / eval_suite versions."""
    commit: str | None = None
    models: list[dict[str, Any]] = Field(default_factory=list)
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    containers: list[dict[str, Any]] = Field(default_factory=list)
    eval_results: dict[str, Any] = Field(default_factory=dict)
    clearances: dict[str, Any] = Field(default_factory=dict)
    files: dict[str, str] = Field(default_factory=dict)
    build_hash: str = ""
    promotions: list[dict[str, Any]] = Field(default_factory=list)


class ReleaseBuilder:
    def __init__(self, root: Path, signer: Signer, ledger: Ledger | None = None) -> None:
        self.root = root
        self.signer = signer
        self.ledger = ledger

    def build(self, name: str, *, components: dict[str, str] | None = None, models: list[dict] | None = None,
              datasets: list[dict] | None = None, eval_results: dict | None = None,
              clearances: dict | None = None, containers: list[dict] | None = None,
              license_engine: LicenseEngine | None = None, commit: str | None = None) -> Path:
        out = self.root / name
        out.mkdir(parents=True, exist_ok=True)
        pkgs = installed_package_licenses()
        docs: dict[str, Any] = {
            "sbom.json": sbom(),
            "mlbom.json": cyclonedx(packages=pkgs),
            "licenses.json": [p.model_dump() for p in pkgs],
            "models.json": models or [],
            "datasets.json": datasets or [],
            "containers.json": containers or [],
            "eval-results.json": eval_results or {},
            "policy-report.json": (clearances or {}).get("policy", {}),
            "ip-clearance.json": (clearances or {}).get("ip", {}),
            "security-report.json": (clearances or {}).get("security", {}),
            "provenance.json": {"ledger_events": len(self.ledger) if self.ledger else 0,
                                "ledger_head": next(reversed(list(self.ledger.events())), None).event_hash
                                if self.ledger and len(self.ledger) else None},
        }
        for fname, data in docs.items():
            (out / fname).write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        write_notices(out, pkgs, models or [], datasets or [])
        files = {p.name: sha256_file(p) for p in sorted(out.iterdir()) if p.is_file()
                 and p.name not in ("hydra-manifest.json", "hashes.sha256", "signature.sig")}
        manifest = ReleaseManifest(
            release=name, components={"core": hydra.__version__, **(components or {})}, commit=commit,
            models=models or [], datasets=datasets or [], containers=containers or [],
            eval_results=eval_results or {}, clearances=clearances or {}, files=files)
        manifest.build_hash = sha256_hex(canonical_json(manifest.model_dump(exclude={"build_hash"})))
        (out / "hydra-manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        hashes = "\n".join(f"{h}  {n}" for n, h in sorted({**files, "hydra-manifest.json":
                                                           sha256_file(out / "hydra-manifest.json")}.items())) + "\n"
        (out / "hashes.sha256").write_text(hashes, encoding="utf-8")
        (out / "signature.sig").write_text(json.dumps(self.signer.envelope(sha256_hex(hashes)), indent=2),
                                           encoding="utf-8")
        if self.ledger is not None:
            self.ledger.append(LedgerEventType.RELEASE_CREATED, {"release": name, "build_hash": manifest.build_hash,
                                                                 "hashes_digest": sha256_hex(hashes)},
                               object_type="release", object_id=name)
        return out


def verify_release(path: Path, trusted_keys: set[str] | None = None) -> dict[str, Any]:
    hashes_txt = (path / "hashes.sha256").read_text(encoding="utf-8")
    env = json.loads((path / "signature.sig").read_text(encoding="utf-8"))
    sig_ok = env.get("digest") == sha256_hex(hashes_txt) and verify_envelope(env, trusted_keys)
    bad = []
    for line in hashes_txt.splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        if not (path / name).exists() or sha256_file(path / name) != digest:
            bad.append(name)
    return {"release": path.name, "signature_valid": sig_ok, "files_ok": not bad, "corrupt": bad,
            "ok": sig_ok and not bad, "key_id": env.get("key_id")}


def promote(path: Path, to_env: str, gates: dict[str, bool], signer: Signer, ledger: Ledger | None = None
            ) -> ReleaseManifest:
    """DEV -> LAB -> STAGING -> CANARY -> PRODUCTION, one step at a time, all gates green."""
    manifest = ReleaseManifest.model_validate_json((path / "hydra-manifest.json").read_text(encoding="utf-8"))
    state_path = path / "promotion.json"  # the signed manifest is immutable; promotions live beside it
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        manifest.environment, manifest.promotions = state["environment"], state["history"]
    cur = ENVIRONMENTS.index(manifest.environment)
    nxt = ENVIRONMENTS.index(to_env)
    if nxt != cur + 1:
        raise ValueError(f"promotion must be sequential: {manifest.environment} -> "
                         f"{ENVIRONMENTS[min(cur + 1, len(ENVIRONMENTS) - 1)]}")
    failed = [g for g, ok in gates.items() if not ok]
    if failed:
        raise PermissionError(f"gates not passed: {failed}")
    manifest.promotions.append({"from": manifest.environment, "to": to_env, "at": now_iso(), "gates": gates})
    manifest.environment = to_env
    write_text_atomic(state_path, json.dumps({"environment": to_env, "history": manifest.promotions,
                                              "signature": signer.envelope(sha256_hex(canonical_json(
                                                  manifest.promotions)))}, indent=2))
    if ledger is not None:
        ledger.append(LedgerEventType.RELEASE_APPROVED, {"release": manifest.release, "environment": to_env,
                                                         "gates": gates}, object_type="release",
                      object_id=manifest.release)
    return manifest


def write_notices(out: Path, pkgs: list[LicenseRecord], models: list[dict], datasets: list[dict]) -> None:
    holder = "Luis Manuel Cousido Hermida"
    (out / "LICENSES.md").write_text(
        f"# Licenses\n\nHYDRA: Copyright (c) 2026 {holder}. All rights reserved. Proprietary.\n\n"
        + "\n".join(f"- {p.artifact_id}: {p.license_id}" for p in pkgs) + "\n", encoding="utf-8")
    (out / "NOTICE.md").write_text(
        f"# NOTICE\n\nHYDRA OS\nCopyright (c) 2026 {holder}. All rights reserved.\n\n"
        "Third-party components remain the property of their owners (see THIRD_PARTY.md).\n", encoding="utf-8")
    (out / "THIRD_PARTY.md").write_text(
        "# Third-party components\n\n| Component | License |\n|---|---|\n"
        + "\n".join(f"| {p.artifact_id.removeprefix('pypi:')} | {p.license_id} |" for p in pkgs) + "\n",
        encoding="utf-8")
    (out / "MODEL_CARD.md").write_text(
        "# Model card\n\n" + ("\n".join(f"## {m.get('id', m.get('model_id', '?'))}\n\n```json\n"
                                        f"{json.dumps(m, indent=2, default=str)[:4000]}\n```" for m in models)
                              or "No models in this release.") + "\n", encoding="utf-8")
    (out / "DATASET_CARD.md").write_text(
        "# Dataset card\n\n" + ("\n".join(f"## {d.get('id', '?')}\n\n```json\n"
                                          f"{json.dumps(d, indent=2, default=str)[:4000]}\n```" for d in datasets)
                                or "No datasets in this release.") + "\n", encoding="utf-8")
