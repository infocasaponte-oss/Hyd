# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Dataset Factory: canonical corpus -> reproducible, rights-aware training datasets.

    query corpus -> filter -> rights policy -> synthetic policy -> balance -> dedupe -> sample
    -> split (train/validation/test/holdout/temporal_holdout/adversarial_holdout) -> compile -> export

Compilers turn the single canonical format into SFT, DPO, KTO, reward, tool-calling,
process-supervision, embedding, reranker, planner and value-model datasets, so the raw
data never has to be rebuilt when a training format changes. Every release is frozen
(manifest + checksums + dataset card + rights/contamination reports) and never "latest"."""

from __future__ import annotations

import hashlib
import json
import random
import math
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from hydra.core.hashing import hash_obj, now_iso, sha256_file
from hydra.corpus.records import Classification, CorpusRecord, RecordType
from hydra.corpus.store import CorpusStore, write_table
from hydra.corpus.artifact_datasets import DatasetFactory as ArtifactDatasetFactory
from hydra.corpus.artifact_datasets import DatasetManifest as ArtifactDatasetManifest
from hydra.corpus.artifact_candidates import CorpusRecord as ArtifactCorpusRecord


class SyntheticPolicy(BaseModel):
    max_fraction: float = Field(default=0.35, ge=0, lt=1, allow_inf_nan=False)
    max_generation: int = Field(default=1, ge=0)
    require_verification: float = Field(default=0.90, ge=0, le=1, allow_inf_nan=False)
    require_real_anchor: bool = True


class DatasetRightsPolicy(BaseModel):
    target_use: str = "internal_model"
    """internal_model | commercial_model | open_model | public-model | cloud_training"""
    allow_confidential: bool = False
    allow_trade_secret: bool = False
    allowed_license_classes: list[str] = Field(default_factory=lambda: ["proprietary", "permissive", "internal"])
    redistribution_required: bool = False
    tenant_id: str | None = None


class DatasetSpec(BaseModel):
    name: str
    version: str = "1"
    record_types: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    capability: str | None = None
    min_quality: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    min_verification: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    languages: dict[str, float] = Field(default_factory=dict)
    """Target language mix, e.g. {es: 0.3, en: 0.45, other: 0.25}."""
    difficulty: dict[str, float] = Field(default_factory=dict)
    """easy/medium/hard mix (curriculum)."""
    max_examples: int | None = Field(default=None, gt=0)
    format: str = "sft"
    """sft | dpo | kto | reward | tool | process | embedding | reranker | planner | value | raw"""
    splits: dict[str, float] = Field(default_factory=lambda: {"train": 0.9, "validation": 0.05, "test": 0.05})
    temporal_holdout_after: str | None = None
    adversarial_holdout: bool = True
    synthetic: SyntheticPolicy = Field(default_factory=SyntheticPolicy)
    rights: DatasetRightsPolicy = Field(default_factory=DatasetRightsPolicy)
    include_statuses: list[str] = Field(default_factory=lambda: ["CURATED", "GOLD"])
    seed: int = 17

    @field_validator("name", "version")
    @classmethod
    def safe_identifier(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
            raise ValueError("dataset name/version must be a safe identifier")
        return value

    @field_validator("splits", "languages", "difficulty")
    @classmethod
    def valid_mix(cls, value: dict[str, float], info) -> dict[str, float]:
        if info.field_name == "splits" and not value:
            raise ValueError("at least one split is required")
        for name, weight in value.items():
            cls.safe_identifier(name)
            if info.field_name == "splits" and name in {"holdout", "temporal_holdout", "adversarial_holdout"}:
                raise ValueError("reserved holdout name")
            if not math.isfinite(weight) or weight < 0:
                raise ValueError("weights must be finite and nonnegative")
        if value and sum(value.values()) <= 0:
            raise ValueError("weights must have a positive total")
        return value

    @classmethod
    def from_yaml(cls, path: str | Path) -> DatasetSpec:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        filters = data.pop("filters", {}) or {}
        balance = data.pop("balance", {}) or {}
        mapped = {
            "record_types": filters.get("record_type", data.get("record_types", [])),
            "min_verification": filters.get("min_verification", data.get("min_verification", 0.0)),
            "min_quality": filters.get("min_quality", data.get("min_quality", 0.0)),
            "domains": filters.get("domains", data.get("domains", [])),
        }
        langs = filters.get("languages") or data.get("languages") or {}
        if isinstance(langs, list):
            langs = {lang: 1 / len(langs) for lang in langs}
        if "synthetic_max_fraction" in filters:
            data.setdefault("synthetic", {})["max_fraction"] = filters["synthetic_max_fraction"]
        if (r := filters.get("rights")) and isinstance(r, dict) and "target_use" in r:
            data.setdefault("rights", {})["target_use"] = r["target_use"]
        return cls(**{**data, **mapped, "languages": langs, "difficulty": balance.get("difficulty", {})})


class DatasetRelease(BaseModel):
    id: str
    name: str
    version: str
    created_at: str = Field(default_factory=now_iso)
    path: str
    format: str
    examples: int
    splits: dict[str, int]
    record_ids_hash: str
    corpus_snapshot: str | None = None
    language_distribution: dict[str, float] = Field(default_factory=dict)
    domain_distribution: dict[str, float] = Field(default_factory=dict)
    synthetic_fraction: float = 0.0
    licenses: dict[str, int] = Field(default_factory=dict)
    quality_distribution: dict[str, int] = Field(default_factory=dict)
    files: dict[str, str] = Field(default_factory=dict)
    """relative path -> sha256"""
    spec: dict[str, Any] = Field(default_factory=dict)
    rejected: dict[str, int] = Field(default_factory=dict)
    parent: str | None = None


# ------------------------------------------------------------------------------ compilers
def compile_record(rec: CorpusRecord, fmt: str) -> dict | None:
    i, o, c = rec.input, rec.output, rec.content
    prompt = i.get("prompt") or i.get("query") or i.get("problem") or i.get("task") or i.get("objective")
    match fmt:
        case "sft":
            if rec.record_type == RecordType.SFT and o.get("messages"):
                return {"messages": o["messages"]}
            if rec.record_type == RecordType.ROUTING_DECISION:
                return {"messages": [{"role": "user", "content": prompt},
                                     {"role": "assistant", "content": json.dumps(o, ensure_ascii=False)}]}
            if rec.record_type == RecordType.CODE_DEBUG and o.get("patch"):
                return {"messages": [{"role": "user", "content": prompt},
                                     {"role": "assistant", "content": f"```python\n{o['patch']}\n```\n{o.get('explanation', '')[:1500]}"}]}
            if rec.record_type == RecordType.TRANSLATION:
                return {"messages": [{"role": "user", "content": prompt}, {"role": "assistant",
                                                                          "content": o.get("translation", "")}]}
            if prompt and (ans := o.get("answer") or o.get("final_answer")):
                return {"messages": [{"role": "user", "content": prompt}, {"role": "assistant", "content": ans}]}
            return None
        case "dpo":
            if rec.record_type == RecordType.PREFERENCE:
                return {"prompt": prompt, "chosen": o["chosen"], "rejected": o["rejected"]}
            return None
        case "kto":
            if rec.record_type == RecordType.SFT and prompt:
                return {"prompt": prompt, "completion": o.get("answer", ""), "label": rec.verification >= 0.9}
            if rec.record_type == RecordType.PREFERENCE:
                return {"prompt": prompt, "completion": o["rejected"], "label": False}
            return None
        case "reward":
            if rec.record_type == RecordType.PREFERENCE:
                return {"prompt": prompt, "chosen": o["chosen"], "rejected": o["rejected"],
                        "margin": round(c.get("chosen_quality", 1) - c.get("rejected_quality", 0), 3)}
            return None
        case "tool":
            if rec.record_type == RecordType.TOOL_USE:
                return {"prompt": prompt, "available_tools": i.get("available_tools", []),
                        "expected_tool_call": rec.action, "tool_result": o.get("tool_result"),
                        "final_answer": o.get("final_answer")}
            return None
        case "process":
            if rec.record_type == RecordType.PROCESS_SUPERVISION:
                return {"prompt": prompt, "completions": c.get("steps", []), "labels": c.get("labels", [])}
            return None
        case "planner":
            if rec.record_type in (RecordType.PLAN, RecordType.ACTION, RecordType.STATE_TRANSITION):
                return {"state": rec.state, "chosen_action": rec.action, "outcome": o, "reward": rec.reward}
            return None
        case "value":
            if rec.record_type in (RecordType.PLAN, RecordType.ACTION, RecordType.ACTION_VALUE) and rec.reward is not None:
                return {"state": rec.state, "action": rec.action, "value": rec.reward}
            return None
        case "embedding":
            if prompt and (ans := o.get("answer")):
                return {"anchor": prompt, "positive": ans[:2000]}
            return None
        case "reranker":
            if rec.record_type == RecordType.PREFERENCE:
                return {"query": prompt, "positive": o["chosen"][:2000], "negative": o["rejected"][:2000]}
            return None
        case _:
            return rec.model_dump(mode="json")


def difficulty_bucket(rec: CorpusRecord) -> str:
    d = rec.difficulty
    if d is None:
        d = 0.8 if "hard" in rec.flags or "frontier" in rec.flags else 0.3
    return "easy" if d < 0.34 else "medium" if d < 0.67 else "hard"


LICENSE_CLASS = {"proprietary": "proprietary", "internal": "internal", "mit": "permissive", "apache-2.0": "permissive",
                 "bsd-3-clause": "permissive", "bsd-2-clause": "permissive", "cc0-1.0": "permissive",
                 "cc-by-4.0": "permissive", "cc-by-sa-4.0": "copyleft", "gpl-3.0": "copyleft",
                 "cc-by-nc-4.0": "non-commercial"}


class DatasetFactory:
    def release_artifacts(
        self, name: str, records: list[ArtifactCorpusRecord], *, root: str | Path
    ) -> ArtifactDatasetManifest:
        """Freeze an artifact-candidate manifest; this does not export training text."""
        return ArtifactDatasetFactory(root).release(name, records)

    def __init__(self, store: CorpusStore, ledger=None) -> None:
        self.store = store
        self.ledger = ledger
        self.releases_dir = store.root / "releases"

    # ------------------------------------------------------------------ selection
    def _rights_ok(self, r: CorpusRecord, pol: DatasetRightsPolicy) -> tuple[bool, str]:
        if not r.rights.training_allowed:
            return False, "training_not_allowed"
        if r.classification == Classification.CONFIDENTIAL and not pol.allow_confidential:
            return False, "confidential"
        if r.classification == Classification.TRADE_SECRET and not pol.allow_trade_secret:
            return False, "trade_secret"
        lic = LICENSE_CLASS.get((r.rights.license or "unknown").lower(), "unknown")
        if lic not in pol.allowed_license_classes:
            return False, f"license:{lic}"
        if pol.target_use in ("open_model", "public-model") and r.classification not in (Classification.PUBLIC,):
            return False, "not_public"
        if pol.target_use in ("commercial_model",) and r.rights.commercial_allowed is False:
            return False, "non_commercial"
        if pol.target_use == "cloud_training" and not r.rights.cloud_allowed:
            return False, "cloud_not_allowed"
        if pol.redistribution_required and not r.rights.redistribution_allowed:
            return False, "no_redistribution"
        if pol.tenant_id is not None and r.tenant_id not in (None, pol.tenant_id):
            return False, "tenant"
        return True, ""

    def select(self, spec: DatasetSpec) -> tuple[list[CorpusRecord], Counter]:
        rejected: Counter = Counter()
        pool = []
        for r in self.store.records.values():
            if r.id in self.store.tombstones:
                rejected["tombstoned"] += 1
                continue
            if r.training_status.value not in spec.include_statuses:
                rejected[f"status:{r.training_status.value}"] += 1
                continue
            if spec.record_types and r.record_type.value not in spec.record_types:
                continue
            if spec.domains and not set(spec.domains) & set(r.domain):
                continue
            if spec.capability and not any(c.startswith(spec.capability) for c in r.capabilities):
                continue
            if r.quality < spec.min_quality or r.verification < spec.min_verification:
                rejected["quality"] += 1
                continue
            ok, why = self._rights_ok(r, spec.rights)
            if not ok:
                rejected[why] += 1
                continue
            if r.synthetic:
                if r.synthetic_generation > spec.synthetic.max_generation:
                    rejected["synthetic_generation"] += 1
                    continue
                if r.verification < spec.synthetic.require_verification:
                    rejected["synthetic_unverified"] += 1
                    continue
                if spec.synthetic.require_real_anchor and not r.provenance.get("source_records"):
                    rejected["synthetic_no_anchor"] += 1
                    continue
            pool.append(r)
        rng = random.Random(spec.seed)
        real = [r for r in pool if not r.synthetic]
        synth = [r for r in pool if r.synthetic]
        max_synth = int(spec.synthetic.max_fraction / max(1e-9, 1 - spec.synthetic.max_fraction) * len(real))
        rng.shuffle(synth)
        if len(synth) > max_synth:
            rejected["synthetic_fraction_cap"] += len(synth) - max_synth
            synth = synth[:max_synth]
        pool = real + synth
        pool = self._balance(pool, spec, rng)
        if spec.max_examples and len(pool) > spec.max_examples:
            rng.shuffle(pool)
            pool = pool[:spec.max_examples]
        return pool, rejected

    @staticmethod
    def _quota(pool: list[CorpusRecord], key, mix: dict[str, float], rng: random.Random) -> list[CorpusRecord]:
        if not mix:
            return pool
        groups: dict[str, list[CorpusRecord]] = defaultdict(list)
        for r in pool:
            k = key(r)
            groups[k if k in mix else "other"].append(r)
        # largest total N such that every bucket can fill its share
        missing = [k for k, w in mix.items() if w > 0 and not groups.get(k)]
        if missing:
            raise ValueError(f"required dataset coverage missing: {', '.join(missing)}")
        total_weight = sum(mix.values())
        mix = {k: w / total_weight for k, w in mix.items() if w > 0}
        feasible = [len(groups[k]) / w for k, w in mix.items()]
        if not feasible:
            return pool
        n = int(min(feasible))
        out = []
        for k, w in mix.items():
            items = groups.get(k, [])
            rng.shuffle(items)
            out.extend(items[: max(1, round(n * w)) if items else 0])
        return out

    def _balance(self, pool: list[CorpusRecord], spec: DatasetSpec, rng: random.Random) -> list[CorpusRecord]:
        pool = self._quota(pool, lambda r: r.language or "other", spec.languages, rng)
        return self._quota(pool, difficulty_bucket, spec.difficulty, rng)

    # ------------------------------------------------------------------ splits
    def split(self, recs: list[CorpusRecord], spec: DatasetSpec) -> dict[str, list[CorpusRecord]]:
        # Connected provenance components keep anchors and their variants together.
        parent: dict[str, str] = {}
        def find(key: str) -> str:
            parent.setdefault(key, key)
            if parent[key] != key:
                parent[key] = find(parent[key])
            return parent[key]
        def union(a: str, b: str) -> None:
            a, b = find(a), find(b)
            parent[max(a, b)] = min(a, b)
        for r in recs:
            key = f"record:{r.id}"
            find(key)
            for field in ("family_id", "source_family_id"):
                value = r.provenance.get(field) or r.metadata.get(field)
                if value:
                    union(key, f"family:{value}")
            if r.source_task_id:
                union(key, f"task:{r.source_task_id}")
            if r.source_id:
                union(key, f"source:{r.source_type}:{r.source_id}")
            anchors = r.provenance.get("source_records", [])
            if isinstance(anchors, str):
                anchors = [anchors]
            for anchor in anchors:
                union(key, f"record:{anchor}")
        groups: dict[str, list[CorpusRecord]] = defaultdict(list)
        for r in recs:
            groups[find(f"record:{r.id}")].append(r)
        out = {k: [] for k in spec.splits}
        out["holdout"] = []
        if spec.temporal_holdout_after:
            out["temporal_holdout"] = []
        if spec.adversarial_holdout:
            out["adversarial_holdout"] = []
        total = sum(spec.splits.values())
        for family, items in sorted(groups.items()):
            h = int(hashlib.sha256(f"{spec.seed}:{family}".encode()).hexdigest()[:8], 16) / 2**32
            if spec.temporal_holdout_after and any(r.created_at >= spec.temporal_holdout_after for r in items):
                target = "temporal_holdout"
            elif spec.adversarial_holdout and any("adversarial" in r.flags for r in items):
                target = "adversarial_holdout"
            elif h >= 0.98 and any(not r.synthetic for r in items):
                target = "holdout"
            else:
                # Synthetic-only families also occupy the full split interval.
                if any(not r.synthetic for r in items):
                    h /= 0.98
                acc = 0.0
                for target, weight in spec.splits.items():
                    acc += weight / total
                    if h < acc:
                        break
            out[target].extend(items)
        return {k: v for k, v in out.items() if v or k in spec.splits}

    # ------------------------------------------------------------------ build
    def build(self, spec: DatasetSpec, snapshot: bool = True) -> DatasetRelease:
        release_id = f"{spec.name}-v{spec.version}"
        destination = (self.releases_dir / release_id).resolve()
        if destination.parent != self.releases_dir.resolve():
            raise ValueError("release path escapes dataset root")
        if destination.exists():
            raise FileExistsError(f"dataset release is immutable: {release_id}")
        stage = Path(tempfile.mkdtemp(prefix=".building-", dir=self.releases_dir))
        try:
            release, selected_ids = self._build_staged(spec, snapshot, stage, destination)
            # The nonempty directory rename refuses a competing published release.
            stage.rename(destination)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        for record_id in selected_ids:
            self.store.add_lineage(record_id, f"dataset:{release_id}", "dataset_release")
        if self.ledger is not None:
            self.ledger.append("DATASET_RELEASED", {
                "release": release_id, "examples": release.examples, "files": release.files,
                "snapshot": release.corpus_snapshot, "record_ids_hash": release.record_ids_hash,
                "target_use": spec.rights.target_use}, object_type="dataset", object_id=release_id)
        return release

    def _build_staged(self, spec: DatasetSpec, snapshot: bool, out_dir: Path,
                      destination: Path) -> tuple[DatasetRelease, list[str]]:
        recs, rejected = self.select(spec)
        splits = self.split(recs, spec)
        release_id = f"{spec.name}-v{spec.version}"
        files: dict[str, str] = {}
        counts: dict[str, int] = {}
        compiled_total = 0
        for name, items in splits.items():
            rows = [x for x in (compile_record(r, spec.format) for r in items) if x is not None]
            counts[name] = len(rows)
            compiled_total += len(rows)
            path = write_table(out_dir / name, rows)
            files[path.name] = sha256_file(path)
        total = len(recs) or 1
        snap = self.store.snapshot().id if snapshot else None
        release = DatasetRelease(
            id=release_id, name=spec.name, version=spec.version, path=str(destination), format=spec.format,
            examples=compiled_total, splits=counts, record_ids_hash=hash_obj(sorted(r.id for r in recs)),
            corpus_snapshot=snap,
            language_distribution={k: round(v / total, 3) for k, v in Counter(r.language or "unknown" for r in recs).items()},
            domain_distribution={k: round(v / total, 3) for k, v in Counter(d for r in recs for d in r.domain).items()},
            synthetic_fraction=round(sum(r.synthetic for r in recs) / total, 3),
            licenses=dict(Counter((r.rights.license or "unknown") for r in recs)),
            quality_distribution=dict(Counter(r.tier.value for r in recs)),
            files=files, spec=spec.model_dump(mode="json"), rejected=dict(rejected))
        (out_dir / "manifest.json").write_text(release.model_dump_json(indent=2), encoding="utf-8")
        (out_dir / "rights-report.json").write_text(json.dumps({
            "target_use": spec.rights.target_use, "licenses": release.licenses,
            "classifications": dict(Counter(r.classification.value for r in recs)),
            "rejected": release.rejected}, indent=2), encoding="utf-8")
        guard = self.store.curator.contamination
        (out_dir / "contamination-report.json").write_text(json.dumps({
            "checked": guard is not None,
            "contaminated": sum(1 for r in recs if guard and guard.contaminated(r)),
            "eval_hashes": len(guard.exact) if guard else 0}, indent=2), encoding="utf-8")
        (out_dir / "dataset-card.json").write_text(json.dumps({
            "name": spec.name, "version": spec.version, "format": spec.format,
            "language": release.language_distribution, "domains": release.domain_distribution,
            "license": "proprietary - Luis Manuel Cousido Hermida. All rights reserved.",
            "origin": "HYDRA verified execution traces (+ labelled synthetic data)",
            "synthetic_fraction": release.synthetic_fraction, "splits": counts,
            "created_at": release.created_at}, indent=2, ensure_ascii=False), encoding="utf-8")
        (out_dir / "checksums.txt").write_text("\n".join(f"{h}  {n}" for n, h in sorted(files.items())) + "\n",
                                               encoding="utf-8")
        return release, [r.id for r in recs]

    def releases(self) -> list[DatasetRelease]:
        out = []
        for m in sorted(self.releases_dir.glob("*/manifest.json")):
            out.append(DatasetRelease.model_validate_json(m.read_text(encoding="utf-8")))
        return out

    def verify_release(self, release_id: str) -> dict[str, Any]:
        rel = next(r for r in self.releases() if r.id == release_id)
        bad = [n for n, h in rel.files.items() if sha256_file(Path(rel.path) / n) != h]
        return {"release": release_id, "ok": not bad, "corrupt": bad}
