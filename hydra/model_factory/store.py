# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Factory store: artifacts, variants, lineage, jobs + the Logical Model Resolver.

    await models.resolve("hydra-reasoner", {"quality": 0.95, "max_memory_gb": 12, "local": True})
    -> hydra-reasoner-14b-q5_k_m.gguf here, hydra-reasoner-14b-fp8 on another server.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from hydra.core.docstore import DocumentStore, KeyedModels
from hydra.model_factory.hardware import HardwareProfile, preferred_formats
from hydra.model_factory.manifest import FactoryJob, ModelArtifact, ModelFormat, ModelLineage, ModelVariant


class ResolveConstraints(BaseModel):
    quality: float | None = None
    max_memory_gb: float | None = None
    local: bool | None = None
    formats: list[ModelFormat] | None = None
    min_tokens_per_second: float | None = None
    hardware: HardwareProfile | None = None
    include_unapproved: bool = False


class FactoryStore:
    """Factory registry: artifacts, variants, lineage and jobs, one ``hydra.core.docstore`` document
    each (``models/<name>.json``, or PostgreSQL shared by the gateway, the factory workers and every
    other node). Each write changes one entry on the latest document."""

    def __init__(self, root: Path, docs: DocumentStore | None = None) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        docs = self.docs = docs or DocumentStore()

        def registry(name: str, model: type[BaseModel]) -> KeyedModels:
            return KeyedModels(docs.document(f"models/{name}", root / name), model)

        self._artifacts = registry("artifacts.json", ModelArtifact)
        self._variants = registry("variants.json", ModelVariant)
        self._lineage = registry("lineage.json", ModelLineage)
        self._jobs = registry("jobs.json", FactoryJob)

    @property
    def artifacts(self) -> dict[str, ModelArtifact]:
        return self._artifacts.all()

    @property
    def variants(self) -> dict[str, ModelVariant]:
        return self._variants.all()

    @property
    def lineage(self) -> dict[str, ModelLineage]:
        return self._lineage.all()

    @property
    def jobs(self) -> dict[str, FactoryJob]:
        return self._jobs.all()

    def dir_for(self, logical: str) -> Path:
        d = self.root / "builds" / logical.replace("/", "_").replace(":", "_")
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------------ artifacts
    def add_artifact(self, a: ModelArtifact, lineage: ModelLineage) -> ModelArtifact:
        self._lineage.put(a.id, lineage)
        return self._artifacts.put(a.id, a)

    def source_of(self, logical: str) -> ModelArtifact | None:
        cands = [a for a in self.artifacts.values() if a.logical_model == logical and a.parent_id is None]
        return max(cands, key=lambda a: a.created_at) if cands else None

    def artifacts_of(self, logical: str) -> list[ModelArtifact]:
        return sorted((a for a in self.artifacts.values() if a.logical_model == logical), key=lambda a: a.created_at)

    def ancestry(self, artifact_id: str) -> list[ModelLineage]:
        chain, seen = [], set()
        todo = [artifact_id]
        while todo:
            aid = todo.pop()
            if aid in seen or aid not in self.lineage:
                continue
            seen.add(aid)
            node = self.lineage[aid]
            chain.append(node)
            todo += node.parent_ids
        return chain

    # ------------------------------------------------------------------ variants
    def upsert_variant(self, v: ModelVariant) -> ModelVariant:
        return self._variants.put(v.id, v)

    def variants_of(self, logical: str) -> list[ModelVariant]:
        return [v for v in self.variants.values() if v.logical_model == logical]

    def logical_models(self) -> list[str]:
        return sorted({a.logical_model for a in self.artifacts.values()})

    # ------------------------------------------------------------------ jobs
    def save_job(self, job: FactoryJob) -> FactoryJob:
        return self._jobs.put(job.id, job)

    def reload_jobs(self) -> None:
        """Kept for callers: ``jobs`` always reflects the stored registry (refreshed per document version)."""
        self._jobs.doc.get()

    # ------------------------------------------------------------------ resolver
    def resolve(self, logical: str, constraints: ResolveConstraints | dict | None = None) -> ModelVariant | None:
        c = constraints if isinstance(constraints, ResolveConstraints) else ResolveConstraints.model_validate(
            constraints or {})
        pool = [v for v in self.variants_of(logical)
                if (v.approved or c.include_unapproved) and v.status != "retired"]
        max_mem = c.max_memory_gb
        if c.hardware is not None:
            max_mem = min(max_mem or 1e9, c.hardware.memory_budget_gb)
        if max_mem is not None:
            pool = [v for v in pool if v.memory_gb <= max_mem]
        if c.quality is not None:
            pool = [v for v in pool if v.quality_score >= c.quality]
        if c.min_tokens_per_second is not None:
            pool = [v for v in pool if v.tokens_per_second >= c.min_tokens_per_second]
        if c.local:
            pool = [v for v in pool if v.runtime in ("ollama", "llamacpp", "mlx", "onnx", "vllm")]
        order = c.formats or (preferred_formats(c.hardware) if c.hardware else None)
        if order:
            pool = [v for v in pool if v.format in order or v.format == ModelFormat.OLLAMA]

        def key(v: ModelVariant):
            fmt_rank = order.index(v.format) if order and v.format in order else len(order or [])
            return (-round(v.quality_score, 2), fmt_rank, -v.tokens_per_second, v.memory_gb)

        return min(pool, key=key) if pool else None
