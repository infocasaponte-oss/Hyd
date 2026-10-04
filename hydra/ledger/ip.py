# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA Provenance & IP Control Plane.

Answers five questions for anything HYDRA creates:
  1. What was created?  2. Who contributed?  3. With which code, data, models and tools?
  4. What technical effect did it produce?  5. Under which rights/licenses may it be used?

HYDRA never decides patentability or inventorship: it records *evidence* (candidate
status only) so a professional can decide with jurisdiction and prior art in mind.
Legal deadlines are data entered by counsel, never hard-coded rules."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

from pydantic import BaseModel, Field

from hydra.core.atomic import write_text_atomic
from hydra.core.eventlog import LogSpace
from hydra.core.hashing import hash_obj, now_iso, sha256_file
from hydra.core.paths import confine, safe_id
from hydra.ledger.chain import Ledger, LedgerEventType


class InventionStatus(str, Enum):
    DISCOVERY = "DISCOVERY"
    CANDIDATE = "CANDIDATE"
    PRIOR_ART_REVIEW = "PRIOR_ART_REVIEW"
    PATENT_REVIEW = "PATENT_REVIEW"
    TRADE_SECRET = "TRADE_SECRET"
    FILED = "FILED"
    PUBLIC = "PUBLIC"
    ABANDONED = "ABANDONED"


class IPStrategy(str, Enum):
    PATENT_CANDIDATE = "PATENT_CANDIDATE"
    TRADE_SECRET = "TRADE_SECRET"
    PUBLICATION = "PUBLICATION"
    OPEN_SOURCE = "OPEN_SOURCE"
    UNDECIDED = "UNDECIDED"


BLOCKING_STATUSES = {InventionStatus.CANDIDATE, InventionStatus.PRIOR_ART_REVIEW, InventionStatus.PATENT_REVIEW,
                     InventionStatus.TRADE_SECRET, InventionStatus.DISCOVERY}
"""Public disclosure of an invention in these states is blocked by the Disclosure Firewall."""


class TechnicalEffect(BaseModel):
    invention_id: str
    metric: str
    baseline_value: float
    experimental_value: float
    unit: str = ""
    lower_is_better: bool = True
    improvement_pct: float = 0.0
    environment_hash: str = ""
    hardware: dict[str, Any] = Field(default_factory=dict)
    software_versions: dict[str, Any] = Field(default_factory=dict)
    benchmark_dataset: str = ""
    experiment_id: str = ""
    sample_size: int = 0
    statistical_summary: dict[str, Any] = Field(default_factory=dict)
    reproducibility_artifact: str = ""


class ContributionRecord(BaseModel):
    contributor_id: str
    invention_id: str
    contribution_type: str
    """CONCEPTION | ARCHITECTURE | ALGORITHM | IMPLEMENTATION | EXPERIMENT | DATASET | EVALUATION | REVIEW"""
    role: str = "inventor_candidate"
    """author | developer | researcher | inventor_candidate | reviewer | dataset_creator | ai_assistant"""
    description: str = ""
    started_at: str | None = None
    recorded_at: str = Field(default_factory=now_iso)
    evidence_refs: list[str] = Field(default_factory=list)
    confirmed_by: list[str] = Field(default_factory=list)


class ModelAssistance(BaseModel):
    actor: str
    role: str = "design_assistant"
    input_hash: str
    output_hash: str
    accepted_parts: list[str] = Field(default_factory=list)
    modified_by_human: bool = True
    reviewer: str | None = None


class PriorArtReference(BaseModel):
    identifier: str
    source: str = "patent"
    publication_date: str = ""
    relevance: float = 0.0
    overlapping_features: list[str] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)
    discovered_at: str = Field(default_factory=now_iso)


class PriorArtSearch(BaseModel):
    id: str = Field(default_factory=lambda: f"PS-{uuid4().hex[:6]}")
    invention_id: str
    search_date: str = Field(default_factory=now_iso)
    queries: list[str] = Field(default_factory=list)
    classifications: list[str] = Field(default_factory=list)
    references: list[PriorArtReference] = Field(default_factory=list)
    searcher: str = ""
    notes: str = ""


class PatentFiling(BaseModel):
    jurisdiction: str
    application_number: str | None = None
    filing_date: str
    priority_claims: list[str] = Field(default_factory=list)
    status: str = "filed"
    attorney: str | None = None
    legal_deadlines: dict[str, str] = Field(default_factory=dict)
    """Entered by counsel (e.g. {"priority_deadline": "2027-09-25"}); never computed by HYDRA."""


class DisclosureRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"DISC-{uuid4().hex[:6]}")
    invention_ids: list[str]
    disclosure_type: str
    """investor_demo | conference | paper | GitHub | model_release | customer_demo | website | email"""
    date: str = Field(default_factory=now_iso)
    audience: str = ""
    confidential: bool = True
    nda_reference: str | None = None
    artifact_hash: str = ""
    public_url: str | None = None


class InventionRecord(BaseModel):
    invention_id: str
    title: str
    status: InventionStatus = InventionStatus.CANDIDATE
    strategy: IPStrategy = IPStrategy.UNDECIDED
    family: str | None = None
    contributors: list[str] = Field(default_factory=list)
    problem: str = ""
    previous_approach: str = ""
    proposed_solution: str = ""
    technical_mechanism: str = ""
    features: list[str] = Field(default_factory=list)
    """Feature map (F1..Fn) used for claim/prior-art matrices."""
    alternative_embodiments: list[str] = Field(default_factory=list)
    measurable_effects: list[TechnicalEffect] = Field(default_factory=list)
    experiments: list[str] = Field(default_factory=list)
    diagrams: list[str] = Field(default_factory=list)
    related_commits: list[str] = Field(default_factory=list)
    related_artifacts: list[str] = Field(default_factory=list)
    prior_art: list[PriorArtSearch] = Field(default_factory=list)
    contributions: list[ContributionRecord] = Field(default_factory=list)
    model_assistance: list[ModelAssistance] = Field(default_factory=list)
    disclosures: list[DisclosureRecord] = Field(default_factory=list)
    filings: list[PatentFiling] = Field(default_factory=list)
    first_internal_timestamp: str = Field(default_factory=now_iso)
    confidentiality: str = "INTERNAL_CONFIDENTIAL"


class IPRegistry:
    """Materialised invention state; every mutation is also an append-only ledger event.

    The state is the replay of ``inventions.jsonl`` (one full record version per change, latest wins), a
    ``hydra.core.eventlog`` log on files or on the PostgreSQL stream ``ip/inventions.jsonl``
    (HYDRA_IP_BACKEND) shared by every node. Each change is a read-modify-write done while the stream is
    locked, on the latest version: two nodes never mint the same ``INV-HYDRA-nnnn`` nor lose each
    other's changes. A ``inventions.json`` snapshot of earlier versions is converted once and kept."""

    def __init__(self, root: Path, ledger: Ledger, logs: LogSpace | None = None, refresh_s: float = 1.0) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.ledger = ledger
        self.refresh_s = refresh_s
        log_path = root / "inventions.jsonl"
        legacy = root / "inventions.json"
        if legacy.exists() and not log_path.exists():
            records = json.loads(legacy.read_text(encoding="utf-8")).values()
            write_text_atomic(log_path, "".join(InventionRecord.model_validate(v).model_dump_json() + "\n"
                                                for v in records))
        self.logs = logs or LogSpace(label="ip")
        self._log = self.logs.open(log_path, "ip/inventions.jsonl")
        self._lock = threading.RLock()
        self._inventions: dict[str, InventionRecord] = {}
        self._seen = 0
        self._synced_at = 0.0
        self._catch_up()

    # ------------------------------------------------------------------ state (replay of the log)
    @property
    def inventions(self) -> dict[str, InventionRecord]:
        if self._log.shared and time.monotonic() - self._synced_at >= self.refresh_s:
            self._catch_up()
        return self._inventions

    def _catch_up(self) -> None:
        with self._lock:
            for seq, line in self._log.read(self._seen):
                inv = InventionRecord.model_validate_json(line)
                self._inventions[inv.invention_id] = inv
                self._seen = seq
            self._synced_at = time.monotonic()

    def _commit(self, make: Callable[[], InventionRecord]) -> InventionRecord:
        """Append the record ``make`` builds from the latest state (read while the stream is locked)."""
        with self._lock:
            def build(seq: int, last: str | None) -> str:
                if self._log.shared:
                    self._catch_up()
                return make().model_dump_json()

            seq, body = self._log.append(build)
            inv = InventionRecord.model_validate_json(body)
            if self._log.shared:
                self._catch_up()
            else:
                self._inventions[inv.invention_id], self._seen = inv, seq
            return inv

    def _change(self, invention_id: str, mutate: Callable[[InventionRecord], None]) -> InventionRecord:
        def make() -> InventionRecord:
            inv = self._inventions[invention_id].model_copy(deep=True)
            mutate(inv)
            return inv

        return self._commit(make)

    def _event(self, et: LedgerEventType, inv: str, payload: dict, actor: str = "hydra") -> None:
        self.ledger.append(et, payload, object_type="invention", object_id=inv, actor_id=actor,
                           confidentiality=self.inventions[inv].confidentiality if inv in self.inventions
                           else "INTERNAL_CONFIDENTIAL")

    def next_id(self) -> str:
        """The next free id (``propose`` assigns it again while the stream is locked)."""
        return f"INV-HYDRA-{len(self.inventions) + 1:04d}"

    # ------------------------------------------------------------------ write
    def propose(self, title: str, *, problem: str = "", solution: str = "", mechanism: str = "",
                previous_approach: str = "", features: list[str] | None = None, contributors: list[str] | None = None,
                status: InventionStatus = InventionStatus.CANDIDATE, actor: str = "hydra",
                family: str | None = None) -> InventionRecord:
        inv = self._commit(lambda: InventionRecord(
            invention_id=f"INV-HYDRA-{len(self._inventions) + 1:04d}", title=title, problem=problem,
            proposed_solution=solution, technical_mechanism=mechanism, previous_approach=previous_approach,
            features=features or [], contributors=contributors or [], status=status, family=family))
        self._event(LedgerEventType.INVENTION_CANDIDATE_CREATED, inv.invention_id,
                    {"title": title, "problem": problem, "mechanism": mechanism, "features": inv.features,
                     "status": status.value}, actor)
        return inv

    def get(self, invention_id: str) -> InventionRecord:
        return self.inventions[invention_id]

    def set_status(self, invention_id: str, status: InventionStatus, actor: str, reason: str = "") -> InventionRecord:
        old: list[InventionStatus] = []

        def mutate(inv: InventionRecord) -> None:
            old[:] = [inv.status]
            inv.status = status
            if status == InventionStatus.TRADE_SECRET:
                inv.strategy = IPStrategy.TRADE_SECRET

        inv = self._change(invention_id, mutate)
        self._event(LedgerEventType.INVENTION_STATUS_CHANGED, invention_id,
                    {"from": old[0].value, "to": status.value, "reason": reason}, actor)
        if status == InventionStatus.PATENT_REVIEW:
            self._event(LedgerEventType.PATENT_REVIEW_STARTED, invention_id, {"reason": reason}, actor)
        return inv

    def add_effect(self, effect: TechnicalEffect) -> TechnicalEffect:
        delta = effect.baseline_value - effect.experimental_value
        if not effect.lower_is_better:
            delta = -delta
        effect.improvement_pct = round(100 * delta / effect.baseline_value, 2) if effect.baseline_value else 0.0
        self._change(effect.invention_id, lambda inv: inv.measurable_effects.append(effect))
        self._event(LedgerEventType.TECHNICAL_EFFECT_OBSERVED, effect.invention_id, effect.model_dump())
        return effect

    def add_contribution(self, c: ContributionRecord) -> ContributionRecord:
        def mutate(inv: InventionRecord) -> None:
            inv.contributions.append(c)
            if c.contributor_id not in inv.contributors and c.role != "ai_assistant":
                inv.contributors.append(c.contributor_id)

        self._change(c.invention_id, mutate)
        self._event(LedgerEventType.CONTRIBUTION_RECORDED, c.invention_id, c.model_dump(), c.contributor_id)
        return c

    def add_model_assistance(self, invention_id: str, a: ModelAssistance) -> ModelAssistance:
        self._change(invention_id, lambda inv: inv.model_assistance.append(a))
        self._event(LedgerEventType.MODEL_ASSISTANCE, invention_id, a.model_dump(), a.actor)
        return a

    def add_prior_art(self, search: PriorArtSearch) -> PriorArtSearch:
        self._change(search.invention_id, lambda inv: inv.prior_art.append(search))
        self._event(LedgerEventType.PRIOR_ART_SEARCH, search.invention_id, search.model_dump(), search.searcher or "hydra")
        return search

    def add_embodiment(self, invention_id: str, text: str) -> None:
        self._change(invention_id, lambda inv: inv.alternative_embodiments.append(text))
        self._event(LedgerEventType.DESIGN_CHANGED, invention_id, {"alternative_embodiment": text})

    def link(self, invention_id: str, *, commit: str | None = None, experiment: str | None = None,
             artifact: str | None = None) -> None:
        def mutate(inv: InventionRecord) -> None:
            if commit:
                inv.related_commits.append(commit)
            if experiment:
                inv.experiments.append(experiment)
            if artifact:
                inv.related_artifacts.append(artifact)

        self._change(invention_id, mutate)
        if commit:
            self._event(LedgerEventType.CODE_COMMIT_REGISTERED, invention_id, {"commit": commit})

    def record_disclosure(self, d: DisclosureRecord) -> DisclosureRecord:
        for i in d.invention_ids:
            self._change(i, lambda inv: inv.disclosures.append(d))
            self._event(LedgerEventType.PUBLIC_DISCLOSURE if not d.confidential else LedgerEventType.DISCLOSURE_CREATED,
                        i, d.model_dump())
        return d

    def record_filing(self, invention_id: str, filing: PatentFiling) -> None:
        def mutate(inv: InventionRecord) -> None:
            inv.filings.append(filing)
            inv.status = InventionStatus.FILED

        self._change(invention_id, mutate)
        self._event(LedgerEventType.PATENT_FILED, invention_id, filing.model_dump())

    # ------------------------------------------------------------------ analysis
    def feature_matrix(self, invention_id: str) -> dict[str, Any]:
        """Features x prior-art references (a technical map for counsel, not a legal claim)."""
        inv = self.inventions[invention_id]
        refs = [r for s in inv.prior_art for r in s.references]
        rows = {f: {r.identifier: f in r.overlapping_features for r in refs} | {"HYDRA": True} for f in inv.features}
        novel = [f for f, row in rows.items() if not any(v for k, v in row.items() if k != "HYDRA")]
        return {"features": rows, "references": [r.identifier for r in refs],
                "features_not_found_in_refs": novel,
                "combination_unique": not any(set(inv.features) <= set(r.overlapping_features) for r in refs)}

    def disclosure_check(self, invention_ids: list[str]) -> tuple[bool, list[str]]:
        blocked = [i for i in invention_ids if i in self.inventions and self.inventions[i].status in BLOCKING_STATUSES]
        return not blocked, blocked

    def first_disclosure(self, invention_id: str) -> DisclosureRecord | None:
        pub = [d for d in self.inventions[invention_id].disclosures if not d.confidential]
        return min(pub, key=lambda d: d.date) if pub else None

    def timeline(self, invention_id: str) -> list[dict[str, Any]]:
        """IP notebook: a verifiable digital lab notebook of the invention."""
        return [{"at": e.created_at, "event": e.event_type, "seq": e.sequence, "hash": e.event_hash[:16],
                 "summary": {k: v for k, v in e.payload.items() if k in ("title", "to", "metric", "commit",
                                                                         "improvement_pct", "contribution_type",
                                                                         "alternative_embodiment", "queries")}}
                for e in self.ledger.for_object("invention", invention_id)]

    def portfolio(self) -> dict[str, Any]:
        fams: dict[str, list[str]] = {}
        for inv in self.inventions.values():
            fams.setdefault(inv.family or "unassigned", []).append(f"{inv.invention_id} {inv.title}")
        status: dict[str, int] = {}
        for inv in self.inventions.values():
            status[inv.status.value] = status.get(inv.status.value, 0) + 1
        return {"families": fams, "status": status, "total": len(self.inventions)}

    def overlaps(self, threshold: float = 0.6) -> list[tuple[str, str, float]]:
        """Detect near-identical invention candidates before filing ten times the same thing."""
        invs = list(self.inventions.values())
        out = []
        for i, a in enumerate(invs):
            for b in invs[i + 1:]:
                fa, fb = set(a.features), set(b.features)
                if fa and fb:
                    j = len(fa & fb) / len(fa | fb)
                    if j >= threshold:
                        out.append((a.invention_id, b.invention_id, round(j, 3)))
        return out


# ------------------------------------------------------------------------------ detectors
class CandidateSignal(BaseModel):
    mechanism: str
    novelty_score: float
    technical_effect: float
    reproducibility: float
    observed_in: int = 0
    related_components: list[str] = Field(default_factory=list)


def should_propose(sig: CandidateSignal, effect_threshold: float = 0.1) -> bool:
    """New mechanism + measurable effect + reproducible -> CANDIDATE (never 'PATENTABLE')."""
    return sig.novelty_score > 0.75 and sig.technical_effect > effect_threshold and sig.reproducibility > 0.9


def mine_innovations(experiments: list[dict[str, Any]], min_tasks: int = 100, min_gain: float = 0.1
                     ) -> list[CandidateSignal]:
    """Innovation mining over HYDRA Lab experiments: repeated, consistent improvements."""
    out = []
    for e in experiments:
        base, cand = e.get("baseline", {}), e.get("candidate", {})
        n = int(cand.get("n", 0))
        if n < min_tasks or not base:
            continue
        gains = []
        for metric, better in (("latency_ms", -1), ("confidence", 1), ("failure_rate", -1), ("cost", -1)):
            if metric in base and metric in cand and base[metric]:
                gains.append(better * (cand[metric] - base[metric]) / abs(base[metric]))
        best = max(gains, default=0)
        if best >= min_gain:
            out.append(CandidateSignal(mechanism=e.get("name", "unnamed"), novelty_score=0.8, technical_effect=best,
                                       reproducibility=min(1.0, n / 1000 + 0.5), observed_in=n,
                                       related_components=[e.get("kind", "config")]))
    return out


# ------------------------------------------------------------------------------ experiments
def environment_manifest() -> dict[str, Any]:
    def run(cmd: list[str]) -> str:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            return ""
    try:
        from importlib.metadata import distributions
        deps = sorted(f"{d.metadata['Name']}=={d.version}" for d in distributions() if d.metadata.get("Name"))
    except Exception:
        deps = []
    gpu = run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"])
    return {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
            "cpu_count": os.cpu_count(), "gpu": gpu or None, "git_commit": run(["git", "rev-parse", "HEAD"]) or None,
            "dependencies_hash": hash_obj(deps), "dependencies": deps[:400]}


class ExperimentRecord(BaseModel):
    experiment_id: str = Field(default_factory=lambda: f"EXP-{uuid4().hex[:6]}")
    invention_id: str | None = None
    name: str
    started_at: str = Field(default_factory=now_iso)
    ended_at: str | None = None
    environment: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None
    model_hashes: dict[str, str] = Field(default_factory=dict)
    dataset_hashes: dict[str, str] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)
    status: str = "running"


@contextmanager
def ip_experiment(ledger: Ledger, name: str, *, invention: str | None = None, parameters: dict | None = None,
                  seed: int | None = None, capsule_dir: Path | None = None) -> Iterator[ExperimentRecord]:
    """Automatic experiment recorder: captures the environment, results and a reproducibility
    capsule; the manifest is hashed into the ledger without anyone remembering to document it."""
    exp = ExperimentRecord(invention_id=invention, name=name, parameters=parameters or {}, seed=seed,
                           environment=environment_manifest())
    ledger.append(LedgerEventType.EXPERIMENT_STARTED, {"experiment": exp.experiment_id, "name": name,
                                                       "invention": invention, "parameters": exp.parameters,
                                                       "environment_hash": hash_obj(exp.environment)},
                  object_type="experiment", object_id=exp.experiment_id)
    started = time.perf_counter()
    try:
        yield exp
        exp.status = "completed"
    except Exception as exc:
        exp.status = f"failed: {exc}"
        raise
    finally:
        exp.ended_at = now_iso()
        exp.results.setdefault("duration_s", round(time.perf_counter() - started, 3))
        if capsule_dir is not None:
            capsule = capsule_dir / exp.experiment_id
            capsule.mkdir(parents=True, exist_ok=True)
            (capsule / "environment.json").write_text(json.dumps(exp.environment, indent=2), encoding="utf-8")
            (capsule / "config.json").write_text(json.dumps(exp.parameters, indent=2, default=str), encoding="utf-8")
            (capsule / "metrics.json").write_text(json.dumps(exp.results, indent=2, default=str), encoding="utf-8")
            (capsule / "input-manifest.json").write_text(json.dumps({"models": exp.model_hashes,
                                                                     "datasets": exp.dataset_hashes}, indent=2),
                                                         encoding="utf-8")
            (capsule / "hashes.txt").write_text("\n".join(f"{sha256_file(p)}  {p.name}" for p in
                                                          sorted(capsule.glob("*.json"))) + "\n", encoding="utf-8")
        ledger.append(LedgerEventType.EXPERIMENT_COMPLETED, {"experiment": exp.experiment_id,
                                                             "status": exp.status, "results": exp.results,
                                                             "manifest_hash": hash_obj(exp.model_dump())},
                      object_type="experiment", object_id=exp.experiment_id)
        if invention:
            ledger.append(LedgerEventType.EXPERIMENT_EXECUTED, {"experiment": exp.experiment_id},
                          object_type="invention", object_id=invention)


# ------------------------------------------------------------------------------ trade secrets
class TradeSecretVault:
    """Encrypted storage (Fernet/AES) with restricted ACL; every access is audited in the ledger."""

    def __init__(self, root: Path, ledger: Ledger, key: bytes | None = None, keystore=None) -> None:
        from cryptography.fernet import Fernet

        from hydra.core.keystore import KeyStore

        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        if key is None:
            store = keystore or KeyStore(root.parent, backend="legacy")
            key = store.get_or_create("ip-vault", root / ".vault.key", Fernet.generate_key)
        self.fernet = Fernet(key)
        self.ledger = ledger
        self.acl_path = root / "acl.json"
        self.acl: dict[str, list[str]] = json.loads(self.acl_path.read_text()) if self.acl_path.exists() else {}

    def put(self, name: str, content: str, allowed: list[str], actor: str) -> None:
        (self.root / f"{name}.enc").write_bytes(self.fernet.encrypt(content.encode()))
        self.acl[name] = sorted(set(allowed) | {actor})
        write_text_atomic(self.acl_path, json.dumps(self.acl, indent=2))
        self.ledger.append(LedgerEventType.TRADE_SECRET_ACCESSED, {"secret": name, "action": "write",
                                                                   "allowed": self.acl[name]},
                           actor_id=actor, object_type="trade_secret", object_id=name,
                           confidentiality="TRADE_SECRET")

    def get(self, name: str, actor: str) -> str:
        allowed = actor in self.acl.get(name, [])
        self.ledger.append(LedgerEventType.TRADE_SECRET_ACCESSED, {"secret": name, "action": "read",
                                                                   "granted": allowed},
                           actor_id=actor, object_type="trade_secret", object_id=name, confidentiality="TRADE_SECRET")
        if not allowed:
            raise PermissionError(f"{actor} may not read trade secret {name}")
        return self.fernet.decrypt((self.root / f"{name}.enc").read_bytes()).decode()


# ------------------------------------------------------------------------------ evidence bundle
def export_bundle(reg: IPRegistry, invention_id: str, out_dir: Path, signer=None, extra: dict | None = None) -> Path:
    """``hydra ip bundle INV-0042``: engineering disclosure package for patent counsel."""
    # the id becomes a directory that is deleted and rewritten: one safe path component only
    root = confine(out_dir, safe_id(invention_id, "invention id"))
    inv = reg.get(invention_id)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    def w(rel: str, data: Any) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False, default=str),
                     encoding="utf-8")

    desc = [f"# {inv.invention_id} — {inv.title}", "", f"Status: {inv.status.value} · Strategy: {inv.strategy.value}",
            "", "## FIELD", "Heterogeneous cognitive systems / AI orchestration.", "",
            "## TECHNICAL PROBLEM", inv.problem, "", "## PREVIOUS APPROACH", inv.previous_approach, "",
            "## MECHANISM", inv.technical_mechanism, "", "## SOLUTION", inv.proposed_solution, "",
            "## FEATURES", *[f"- F{i + 1}: {f}" for i, f in enumerate(inv.features)], "",
            "## ALTERNATIVE EMBODIMENTS", *[f"- {e}" for e in inv.alternative_embodiments], "",
            "## TECHNICAL EFFECTS",
            *[f"- {e.metric}: {e.baseline_value} -> {e.experimental_value} {e.unit} ({e.improvement_pct:+.1f}%)"
              for e in inv.measurable_effects], "",
            "_Engineering disclosure package generated by HYDRA. Not a legal patent application._",
            "Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved."]
    w("00_manifest.json", {"invention": invention_id, "generated_at": now_iso(), "ledger_events": len(reg.ledger)})
    w("01_invention_description.md", "\n".join(desc))
    w("02_contributors.json", {"contributors": inv.contributors, "contributions": [c.model_dump() for c in inv.contributions],
                               "model_assistance": [a.model_dump() for a in inv.model_assistance]})
    w("03_timeline.json", reg.timeline(invention_id))
    w("04_architecture/diagrams.json", inv.diagrams)
    w("05_code_refs/commits.json", inv.related_commits)
    w("06_experiments/experiments.json", [e.model_dump() for e in reg.ledger.events()
                                          if e.object_type == "experiment" and e.object_id in inv.experiments])
    w("07_technical_effects/effects.json", [e.model_dump() for e in inv.measurable_effects])
    w("08_prior_art/searches.json", [s.model_dump() for s in inv.prior_art])
    w("09_feature_matrix/matrix.json", reg.feature_matrix(invention_id))
    w("10_disclosures/disclosures.json", [d.model_dump() for d in inv.disclosures])
    w("11_licenses/licenses.json", (extra or {}).get("licenses", {}))
    w("12_model_boms/boms.json", (extra or {}).get("model_boms", []))
    w("13_dataset_boms/boms.json", (extra or {}).get("dataset_boms", []))
    files = sorted(p for p in root.rglob("*") if p.is_file())
    hashes = "\n".join(f"{sha256_file(p)}  {p.relative_to(root).as_posix()}" for p in files) + "\n"
    (root / "hashes.sha256").write_text(hashes, encoding="utf-8")
    if signer is not None:
        from hydra.core.hashing import sha256_hex

        (root / "signature.sig").write_text(json.dumps(signer.envelope(sha256_hex(hashes)), indent=2), encoding="utf-8")
    return root
