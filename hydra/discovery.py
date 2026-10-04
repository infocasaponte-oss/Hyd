# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Capability Discovery Engine, Replacement Analyzer, model lifecycle and Benchmark Exchange.

    MODEL IMPORT -> static inspection -> capability probing -> adaptive benchmarking
    -> calibration -> hardware benchmark -> profile -> Model Registry

Provider claims are only CLAIMED; what HYDRA measures is MEASURED and governs routing.
Nothing is special by name: models are capability vectors with confidence intervals."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from hydra.core.docstore import DocumentStore, KeyedModels
from hydra.core.atomic import write_text_atomic
from hydra.core.hashing import hash_obj, now_iso
from hydra.evals.suites import EvalCase

ONTOLOGY: dict[str, list[str]] = {
    "reasoning": ["arithmetic", "symbolic", "logical", "planning", "causal", "temporal"],
    "coding": ["generation", "debugging", "review", "refactoring", "testing", "python", "rust", "cpp", "sql"],
    "vision": ["ocr", "document", "ui", "spatial", "charts", "video"],
    "tool_use": ["selection", "schema_following", "argument_generation", "result_interpretation",
                 "multi_tool_planning"],
    "language": ["spanish", "english", "translation", "technical", "galician"],
    "knowledge": ["factual", "abstention"],
    "long_context": ["retrieval_8k", "retrieval_32k"],
}

SUITE_CAPABILITY = {"coding": "coding.python", "reasoning": "reasoning.arithmetic", "tool_use": "tool_use.selection",
                    "json": "tool_use.schema_following", "structured": "tool_use.schema_following",
                    "hallucination": "knowledge.abstention", "vision": "vision.spatial", "abstain": "knowledge.abstention",
                    "knowledge": "knowledge.factual", "language": "language.translation"}


def extra_probes() -> list[EvalCase]:
    """Language / knowledge probes on top of the built-in eval suites."""
    return [
        EvalCase(id="lang-es-1", suite="language", prompt="Traduce al español: 'good morning, my friend'.",
                 grader="regex", expected=r"(?i)buen(os)? d[ií]as"),
        EvalCase(id="lang-en-1", suite="language", prompt="Translate to English: 'el gato duerme en la cocina'.",
                 grader="regex", expected=r"(?i)cat .*sleep.* kitchen"),
        EvalCase(id="lang-gl-1", suite="language", prompt="Traduce ao castelán: 'Bo día, grazas'.",
                 grader="regex", expected=r"(?i)buen(os)? d[ií]as.*gracias"),
        EvalCase(id="know-1", suite="knowledge", prompt="¿Cuál es la capital de Galicia? Responde solo la ciudad.",
                 grader="regex", expected=r"(?i)santiago"),
        EvalCase(id="know-2", suite="knowledge", prompt="What is the chemical symbol of gold? Answer with the symbol.",
                 grader="regex", expected=r"\bAu\b"),
    ]


def wilson(successes: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


class CapabilityScore(BaseModel):
    capability_id: str
    score: float
    uncertainty: float
    lower: float
    upper: float
    sample_size: int
    eval_suite: str
    hardware_ref: str | None = None
    measured_at: str = Field(default_factory=now_iso)
    source: str = "MEASURED"


class CapabilityProfile(BaseModel):
    model_id: str
    fingerprint: dict[str, CapabilityScore] = Field(default_factory=dict)
    claimed: dict[str, float] = Field(default_factory=dict)
    skipped: list[str] = Field(default_factory=list)
    latency_ms: float | None = None
    discovered_at: str = Field(default_factory=now_iso)
    probe_hash: str = ""

    def vector(self) -> dict[str, float]:
        return {k: v.score for k, v in self.fingerprint.items()}


class OntologyProposal(BaseModel):
    capability: str
    parent: str
    evidence: dict[str, Any]
    status: str = "PROPOSED"


class CapabilityDiscovery:
    def __init__(self, evaluator, root: Path) -> None:
        self.evaluator = evaluator
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def cases_by_capability(self) -> dict[str, list[EvalCase]]:
        out: dict[str, list[EvalCase]] = {}
        suites = dict(self.evaluator.suites)
        for c in extra_probes():
            suites.setdefault(c.suite, []).append(c)
        for suite, cases in suites.items():
            cap = SUITE_CAPABILITY.get(suite, f"{suite}.general")
            out.setdefault(cap, []).extend(cases)
        return out

    async def _run(self, model, cases: list[EvalCase]) -> list:
        provider = self.evaluator.providers.get(model.provider) or next(iter(self.evaluator.providers.values()))
        results = []
        for c in cases:
            try:
                results.append(await self.evaluator._run_case(provider, model, c))
            except Exception:
                continue
        return results

    async def discover(self, model, *, broad_per_capability: int = 1, threshold: float = 0.25,
                       hardware_ref: str | None = None) -> CapabilityProfile:
        caps = self.cases_by_capability()
        prof = CapabilityProfile(model_id=model.id, claimed={k: getattr(model.capabilities, k)
                                                             for k in model.capabilities.model_fields},
                                 probe_hash=hash_obj({k: [c.id for c in v] for k, v in caps.items()}))
        lat = []
        for cap, cases in caps.items():
            if cap.startswith("vision") and model.capabilities.vision < 0.3 and not model.quirks.native_images:
                prof.skipped.append(cap)
                continue
            broad = await self._run(model, cases[:broad_per_capability])
            if not broad:
                continue
            broad_score = sum(r.score for r in broad) / len(broad)
            results = broad
            if broad_score >= threshold and len(cases) > broad_per_capability:
                results = broad + await self._run(model, cases[broad_per_capability:])  # adaptive: invest where promising
            n = len(results)
            succ = sum(r.score for r in results)
            lo, hi = wilson(succ, n)
            lat += [r.latency_ms for r in results if r.latency_ms]
            prof.fingerprint[cap] = CapabilityScore(capability_id=cap, score=round(succ / n, 4),
                                                    uncertainty=round((hi - lo) / 2, 4), lower=round(lo, 4),
                                                    upper=round(hi, 4), sample_size=n,
                                                    eval_suite=cases[0].suite, hardware_ref=hardware_ref)
        prof.latency_ms = round(sum(lat) / len(lat), 1) if lat else None
        write_text_atomic(self.root / f"{model.id.replace('/', '_').replace(':', '_')}.json",
                          prof.model_dump_json(indent=2))
        return prof

    def load(self, model_id: str) -> CapabilityProfile | None:
        p = self.root / f"{model_id.replace('/', '_').replace(':', '_')}.json"
        return CapabilityProfile.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None

    @staticmethod
    def apply(profile: CapabilityProfile, registry, min_samples: int = 2) -> dict[str, float]:
        """MEASURED capabilities replace CLAIMED ones in the router-facing profile (lower bound when N is small)."""
        m = registry.get(profile.model_id)
        top: dict[str, list[CapabilityScore]] = {}
        for cap, s in profile.fingerprint.items():
            top.setdefault(cap.split(".")[0], []).append(s)
        mapping = {"coding": "coding", "reasoning": "reasoning", "tool_use": "tools", "vision": "vision",
                   "language": "chat", "knowledge": "chat"}
        applied = {}
        for parent, scores in top.items():
            field = mapping.get(parent)
            if not field:
                continue
            n = sum(s.sample_size for s in scores)
            if n < min_samples:
                continue
            val = sum(s.score * s.sample_size for s in scores) / n
            val = val if n >= 8 else (val + min(s.lower for s in scores)) / 2
            setattr(m.capabilities, field, round(val, 3))
            applied[field] = round(val, 3)
        return applied

    @staticmethod
    def emerging(runs: list, traces: list, clusters: list, min_n: int = 20, margin: float = 0.15,
                 known: set[str] | None = None) -> list[OntologyProposal]:
        """A model doing surprisingly well on an unlabelled task family -> propose a new capability."""
        known = known or {f"{p}.{c}" for p, cs in ONTOLOGY.items() for c in cs} | set(ONTOLOGY)
        by_task = {t.task_id: t for t in traces}
        out = []
        for cl in clusters:
            label = cl.label.split("+")[0]
            ids = {t.task_id for t in traces if cl.examples and t.input.get("prompt", "")[:120] in cl.examples} or set()
            if not ids:
                continue
            stats: dict[str, list[float]] = {}
            for r in runs:
                if str(r.task_id) in ids and r.verifier_score is not None:
                    stats.setdefault(r.model_id, []).append(r.verifier_score)
            ranked = sorted(((sum(v) / len(v), m, len(v)) for m, v in stats.items() if len(v) >= min_n), reverse=True)
            if len(ranked) >= 2 and ranked[0][0] - ranked[1][0] >= margin and label not in known:
                out.append(OntologyProposal(capability=f"emergent.{label}", parent="emergent",
                                            evidence={"model": ranked[0][1], "score": round(ranked[0][0], 3),
                                                      "runner_up": ranked[1][1], "n": ranked[0][2],
                                                      "examples": cl.examples}))
        _ = by_task
        return out


class ReplacementReport(BaseModel):
    candidate: str
    dominates: list[str] = Field(default_factory=list)
    partially_dominates: list[str] = Field(default_factory=list)
    regressions: list[dict[str, Any]] = Field(default_factory=list)
    projected_cost_savings: float = 0.0
    recommended_action: str = "keep_as_candidate"


def analyze_replacement(candidate: CapabilityProfile, incumbents: list[CapabilityProfile],
                        costs: dict[str, float] | None = None, tolerance: float = 0.02) -> ReplacementReport:
    rep = ReplacementReport(candidate=candidate.model_id)
    cv = candidate.fingerprint
    for inc in incumbents:
        if inc.model_id == candidate.model_id:
            continue
        shared = set(cv) & set(inc.fingerprint)
        if not shared:
            continue
        better = [c for c in shared if cv[c].score >= inc.fingerprint[c].score - tolerance]
        worse = [c for c in shared if cv[c].score < inc.fingerprint[c].score - tolerance]
        if len(better) == len(shared):
            rep.dominates.append(inc.model_id)
        elif better:
            rep.partially_dominates.append(inc.model_id)
        rep.regressions += [{"vs": inc.model_id, "capability": c, "candidate": cv[c].score,
                             "incumbent": inc.fingerprint[c].score} for c in worse]
        if costs and inc.model_id in costs and candidate.model_id in costs and len(better) == len(shared):
            rep.projected_cost_savings += max(0.0, costs[inc.model_id] - costs[candidate.model_id])
    rep.recommended_action = ("replace (shadow first): " + ", ".join(rep.dominates) if rep.dominates else
                              "shadow on partially dominated workloads only" if rep.partially_dominates else
                              "keep_as_candidate")
    return rep


LIFECYCLE = ["CANDIDATE", "SHADOW", "ACTIVE", "DEPRECATED", "RETIRED", "ARCHIVED"]


class ModelLifecycle:
    """Retired models keep weights, benchmarks, lineage, license and traces (reproducibility)."""

    def __init__(self, path: Path, docs: DocumentStore | None = None) -> None:
        self.path = path
        self._registry = KeyedModels((docs or DocumentStore()).document("model_lifecycle.json", path))

    @property
    def state(self) -> dict[str, dict[str, Any]]:
        return self._registry.all()

    def status(self, model_id: str) -> str:
        return self.state.get(model_id, {}).get("status", "ACTIVE")

    def transition(self, model_id: str, to: str, reason: str, actor: str = "hydra") -> dict[str, Any]:
        if to not in LIFECYCLE:
            raise ValueError(to)

        def apply(current: dict[str, Any] | None) -> dict[str, Any]:
            cur = current or {"status": "CANDIDATE", "history": []}
            if LIFECYCLE.index(to) < LIFECYCLE.index(cur["status"]) and not (
                    cur["status"] == "DEPRECATED" and to == "ACTIVE"):
                raise ValueError(f"invalid transition {cur['status']} -> {to}")
            cur["history"].append({"from": cur["status"], "to": to, "reason": reason, "by": actor, "at": now_iso()})
            cur["status"] = to
            return cur

        return self._registry.change(model_id, apply)


class BenchmarkContract(BaseModel):
    id: str
    suites: list[str]
    probe_hash: str
    hardware: str
    runtime: str
    quantization: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class BenchmarkEntry(BaseModel):
    contract: BenchmarkContract
    model_id: str
    variant_id: str | None = None
    capabilities: dict[str, float] = Field(default_factory=dict)
    tokens_per_second: float | None = None
    vram_gb: float | None = None
    tool_calling: float | None = None
    languages: list[str] = Field(default_factory=list)
    recorded_at: str = Field(default_factory=now_iso)


class BenchmarkExchange:
    """Reproducible, comparable benchmark records: 'which variant is best for technical Spanish
    with tool-calling in 12 GB VRAM?' answered from HYDRA's own measurements."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[BenchmarkEntry] = []
        if path.exists():
            self.entries = [BenchmarkEntry.model_validate_json(x) for x in path.read_text(encoding="utf-8").splitlines()
                            if x.strip()]

    def record(self, e: BenchmarkEntry) -> None:
        self.entries.append(e)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(e.model_dump_json() + "\n")

    def from_profile(self, prof: CapabilityProfile, hardware: str, runtime: str, variant: Any = None) -> BenchmarkEntry:
        caps = prof.vector()
        e = BenchmarkEntry(contract=BenchmarkContract(id=prof.probe_hash[:12], suites=sorted({s.eval_suite for s in
                                                                                             prof.fingerprint.values()}),
                                                      probe_hash=prof.probe_hash, hardware=hardware, runtime=runtime,
                                                      quantization=getattr(variant, "quantization", None)),
                           model_id=prof.model_id, variant_id=getattr(variant, "id", None), capabilities=caps,
                           tokens_per_second=getattr(variant, "tokens_per_second", None) or None,
                           vram_gb=getattr(variant, "memory_gb", None) or None,
                           tool_calling=caps.get("tool_use.selection"),
                           languages=[x.split(".")[1] for x in caps if x.startswith("language.") and caps[x] >= 0.5])
        self.record(e)
        return e

    def query(self, capability: str, *, max_vram_gb: float | None = None, language: str | None = None,
              tool_calling: bool = False, hardware: str | None = None) -> list[BenchmarkEntry]:
        out = [e for e in self.entries if any(k == capability or k.startswith(capability) for k in e.capabilities)
               and (max_vram_gb is None or (e.vram_gb or 0) <= max_vram_gb)
               and (language is None or language in e.languages or not e.languages)
               and (not tool_calling or (e.tool_calling or 0) >= 0.5)
               and (hardware is None or e.contract.hardware == hardware)]
        return sorted(out, key=lambda e: -max(v for k, v in e.capabilities.items() if k.startswith(capability)))
