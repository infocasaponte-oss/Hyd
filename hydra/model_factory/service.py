# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""ModelFactory: the controlled bridge between Training and Inference.

SOURCE -> INSPECT -> NORMALIZE -> {GGUF, AWQ/GPTQ/FP8, MLX, ONNX} -> QUANTIZE -> VALIDATE
       -> BENCHMARK -> QUALITY GATE -> PARETO -> MODEL REGISTRY -> CANARY (HYDRA Lab)

It runs as a separate worker (``hydra factory worker``): the API only enqueues jobs.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hydra.core.events import EventType, HydraEvent
from hydra.evals.engine import EvalEngine, EvalReport
from hydra.model_factory.adapters import AdapterRegistry, AdapterSpec
from hydra.model_factory.benchmark import OllamaBenchmark, OpenAIBenchmark
from hydra.model_factory.calibration import ImatrixBuilder, build_calibration_text
from hydra.model_factory.converter import converters
from hydra.model_factory.distillation import DatasetBuilder, DatasetManifest, LoRATrainer, TrainingJob
from hydra.model_factory.hardware import HardwareProfile, detect_local, estimate_memory_gb
from hydra.model_factory.importer import ModelImporter
from hydra.model_factory.inspector import inspect
from hydra.model_factory.jit import CognitiveJIT, SpecialistProposal
from hydra.model_factory.manifest import (
    BenchmarkResult,
    BuildNode,
    FactoryJob,
    JobStatus,
    ModelArtifact,
    ModelFormat,
    ModelInspection,
    ModelLineage,
    ModelSource,
    ModelVariant,
    SourceType,
)
from hydra.model_factory.optimizer import Selection, choose_winner
from hydra.model_factory.publisher import Publisher
from hydra.model_factory.quantizer import GGUFQuantizer, OllamaQuantizer, QuantizationPlanner, QuantSpec
from hydra.model_factory.registry_sync import profile_for
from hydra.model_factory.runner import CommandRunner, ToolLocator, ToolMissing
from hydra.model_factory.store import FactoryStore, ResolveConstraints
from hydra.model_factory.validator import GateThresholds, QualityGate
from hydra.providers.ollama import OllamaProvider
from hydra.providers.openai_compatible import OpenAICompatibleProvider
from hydra.registry.models import ModelProfile
from hydra.registry.registry import ModelRegistry
from hydra.scheduler.graph import ExecutionGraph

log = logging.getLogger("hydra.factory")

FULL_PRECISION = {"F32", "F16", "BF16", "MOSTLY_F16", "ALL_F32"}


class ModelFactory:
    def __init__(
        self,
        store: FactoryStore,
        registry: ModelRegistry,
        evaluator: EvalEngine,
        telemetry=None,
        bus=None,
        lab=None,
        runner: CommandRunner | None = None,
        tools: ToolLocator | None = None,
        ollama_url: str = "http://localhost:11434",
        thresholds: GateThresholds | None = None,
    ) -> None:
        self.store = store
        self.registry = registry
        self.evaluator = evaluator
        self.telemetry = telemetry
        self.bus = bus
        self.lab = lab
        self.runner = runner or CommandRunner()
        self.tools = tools or ToolLocator()
        self.ollama_url = ollama_url
        self.importer = ModelImporter(store, self.runner, self.tools)
        self.planner = QuantizationPlanner()
        self.gguf_quantizer = GGUFQuantizer(self.runner, self.tools)
        self.ollama_quantizer = OllamaQuantizer(self.runner, self.tools)
        self.converters = converters(self.runner, self.tools)
        self.imatrix = ImatrixBuilder(self.runner, self.tools)
        self.publisher = Publisher(self.ollama_quantizer)
        self.gate = QualityGate(evaluator, thresholds=thresholds)
        self.datasets = DatasetBuilder(store.root / "datasets")
        self.trainer = LoRATrainer(self.runner, self.tools)
        self.adapters = AdapterRegistry(store.root / "adapters.json", docs=store.docs)
        self.jit = CognitiveJIT()
        self.eval_reports: dict[str, EvalReport] = {}

    @classmethod
    def from_settings(cls, settings, *, registry, evaluator, telemetry=None, bus=None, lab=None,
                      docs=None) -> ModelFactory:
        tools = ToolLocator(Path(settings.llamacpp_dir) if settings.llamacpp_dir else None)
        return cls(FactoryStore(settings.data_dir / "models", docs=docs), registry, evaluator, telemetry, bus, lab,
                   tools=tools, ollama_url=settings.ollama_base_url)

    async def _event(self, what: str, **payload) -> None:
        if self.bus is not None:
            await self.bus.publish(HydraEvent(task_id=uuid.UUID(int=0), type=EventType.FACTORY_JOB,
                                              source="model_factory", payload={"event": what, **payload}))

    # ================================================================== status
    def status(self) -> dict[str, Any]:
        return {
            "toolchain": self.tools.availability(),
            "logical_models": self.store.logical_models(),
            "artifacts": len(self.store.artifacts),
            "variants": {v.id: {"approved": v.approved, "status": v.status, "quality": v.quality_score,
                                "tps": v.tokens_per_second, "memory_gb": v.memory_gb}
                         for v in self.store.variants.values()},
            "jobs": {s.value: sum(1 for j in self.store.jobs.values() if j.status == s) for s in JobStatus},
        }

    # ================================================================== import / inspect
    async def import_model(self, source: ModelSource, logical: str) -> ModelArtifact:
        art = await self.importer.import_model(source, logical)
        await self._event("imported", artifact=art.id, logical=logical)
        return art

    def inspect_artifact(self, artifact_id: str) -> ModelInspection:
        return inspect(self.store.artifacts[artifact_id].path)

    # ================================================================== build graph
    def plan_builds(self, logical: str, target: str | None = None, hardware: HardwareProfile | None = None,
                    quants: list[str] | None = None, formats: list[str] | None = None
                    ) -> tuple[list[BuildNode], list[str]]:
        """DAG of conversions/quantizations for a logical model, plus notes on what cannot be built."""
        src = self.store.source_of(logical)
        if src is None:
            raise KeyError(f"no source artifact for '{logical}': import it first")
        ins = inspect(src.path)
        notes: list[str] = []
        nodes: list[BuildNode] = []
        specs = ([QuantSpec(quant=q.upper()) for q in quants] if quants
                 else self.planner.choose(ins, target, hardware))

        gguf_input = src.id
        if ins.format == ModelFormat.SAFETENSORS and (not formats or "gguf" in formats):
            if not ins.supports_gguf:
                notes.append(f"{ins.architecture} is not supported by llama.cpp: no GGUF build")
            else:
                nodes.append(BuildNode(id="convert-gguf", operation="convert", input_artifact=src.id,
                                       output_format=ModelFormat.GGUF, quantization="BF16",
                                       params={"outtype": "bf16"}))
                gguf_input = "convert-gguf"
        elif ins.format == ModelFormat.GGUF and (ins.quantization or "").upper() not in FULL_PRECISION:
            notes.append(f"source is already quantized ({ins.quantization}); re-quantizing degrades quality - "
                         "import the F16/BF16 weights to build new variants")
            specs = []
        elif ins.format not in (ModelFormat.GGUF, ModelFormat.SAFETENSORS):
            specs = []

        if specs and (gguf_input != src.id or ins.format == ModelFormat.GGUF):
            if any(s.imatrix for s in specs):
                nodes.append(BuildNode(id="imatrix", operation="imatrix", input_artifact=gguf_input,
                                       output_format=ModelFormat.GGUF,
                                       depends_on=[gguf_input] if gguf_input == "convert-gguf" else []))
            for s in specs:
                deps = [d for d in (gguf_input if gguf_input == "convert-gguf" else None,
                                    "imatrix" if s.imatrix else None) if d]
                nodes.append(BuildNode(id=f"quant-{s.quant.lower()}", operation="quantize", input_artifact=gguf_input,
                                       output_format=ModelFormat.GGUF, quantization=s.quant,
                                       params=s.model_dump(), depends_on=deps))
        for fmt in formats or []:
            if fmt in ("mlx", "onnx", "awq", "gptq", "fp8"):
                conv = self.converters[fmt]
                if not conv.supports(ins):
                    notes.append(f"{fmt}: not supported for {ins.architecture}/{ins.format.value}")
                    continue
                nodes.append(BuildNode(id=f"convert-{fmt}", operation="convert", input_artifact=src.id,
                                       output_format=conv.target, quantization=fmt.upper()))
        return nodes, notes

    async def build(self, logical: str, target: str | None = None, hardware: HardwareProfile | None = None,
                    quants: list[str] | None = None, formats: list[str] | None = None) -> dict[str, Any]:
        nodes, notes = self.plan_builds(logical, target, hardware, quants, formats)
        src = self.store.source_of(logical)
        out_dir = self.store.dir_for(logical)
        produced: dict[str, ModelArtifact] = {}
        extras: dict[str, Path] = {}  # side outputs (importance matrix)
        graph = ExecutionGraph()

        def resolve_input(ref: str) -> ModelArtifact:
            return produced[ref] if ref in produced else self.store.artifacts[ref]

        async def run_node(node: BuildNode, _inputs: dict) -> ModelArtifact | None:
            try:
                art = await self._execute(node, resolve_input(node.input_artifact), extras, out_dir)
            except ToolMissing as exc:
                notes.append(f"{node.id}: {exc}")
                return None
            if art is not None:
                produced[node.id] = art
            return art

        for n in nodes:
            graph.add_node(n.id, lambda inputs, n=n: run_node(n, inputs))
        for n in nodes:
            for d in n.depends_on:
                if d in graph.nodes:
                    graph.add_edge(d, n.id)
        if nodes:
            await graph.execute_parallel(max_concurrency=2)
        await self._event("built", logical=logical, artifacts=[a.id for a in produced.values()])
        return {"source": src.id, "planned": [n.model_dump() for n in nodes],
                "artifacts": [a.model_dump(mode="json") for a in produced.values()], "notes": notes}

    async def _execute(self, node: BuildNode, inp: ModelArtifact, extras: dict, out_dir: Path
                       ) -> ModelArtifact | None:
        name = inp.logical_model.replace("/", "_")
        if node.operation == "convert" and node.output_format == ModelFormat.GGUF:
            conv = self.converters["gguf"]
            if not conv.available() and self.tools.binary("ollama"):
                return None  # Ollama can quantize straight from safetensors below
            path, res = await conv.convert(Path(inp.path), out_dir, name, outtype=node.params.get("outtype", "bf16"))
            return self._register(inp, path, res.ok, node, res.stderr)
        if node.operation == "convert":
            fmt = node.id.split("-", 1)[1]
            path, res = await self.converters[fmt].convert(Path(inp.path), out_dir, name)
            return self._register(inp, path, res.ok, node, res.stderr)
        if node.operation == "imatrix":
            if self.tools.binary("llama-imatrix") is None:
                raise ToolMissing("llama-imatrix not installed: quantizing without importance matrix")
            tasks = await self.telemetry.recent_tasks() if self.telemetry else []
            path, res = await self.imatrix.build(inp.path, build_calibration_text(tasks), out_dir / "calibration")
            if not res.ok:
                raise RuntimeError(f"imatrix failed: {res.stderr[-400:]}")
            extras["imatrix"] = path
            return None
        if node.operation == "quantize":
            spec = QuantSpec.model_validate(node.params)
            if self.tools.binary("llama-quantize") is not None and inp.format == ModelFormat.GGUF:
                out = out_dir / f"{name}-{spec.quant.lower()}.gguf"
                imatrix = extras.get("imatrix")
                res = await self.gguf_quantizer.quantize(inp.path, str(out), spec, str(imatrix) if imatrix else None)
                return self._register(inp, out, res.ok, node, res.stderr)
            if self.tools.binary("ollama") is not None:
                oname = f"hydra-{name}-{spec.quant.lower()}:latest".lower().replace("_", "-")
                res = await self.ollama_quantizer.create(oname, inp.path, quant=spec.quant)
                if not res.ok:
                    raise RuntimeError(f"ollama quantize failed: {res.stderr[-400:]}")
                return self._register_ollama(inp, oname, spec.quant, node)
            raise ToolMissing("no quantizer available (install llama.cpp or Ollama)")
        return None

    def _register(self, parent: ModelArtifact, path: Path, ok: bool, node: BuildNode, err: str) -> ModelArtifact:
        if not ok or not path.exists():
            raise RuntimeError(f"{node.id} failed: {err[-400:]}")
        ins = inspect(path)
        from hydra.model_factory.fingerprint import fingerprint
        from hydra.model_factory.gguf import read_gguf
        from hydra.model_factory.importer import RUNTIMES, variant_id_for

        fp = fingerprint(path, read_gguf(path).metadata if ins.format == ModelFormat.GGUF and path.is_file() else None)
        art = ModelArtifact(
            logical_model=parent.logical_model, variant_id=variant_id_for(ins), architecture=ins.architecture,
            parameter_count=ins.parameters or parent.parameter_count, format=ins.format,
            quantization=ins.quantization or node.quantization, path=str(path),
            context_length=ins.context_length or parent.context_length, multimodal=ins.is_multimodal,
            runtime_targets=RUNTIMES.get(ins.format, []), size_bytes=ins.size_bytes, checksum=fp.weights_sha256,
            fingerprint=fp, parent_id=parent.id, metadata={"node": node.model_dump()})
        return self.store.add_artifact(art, ModelLineage(
            artifact_id=art.id, parent_ids=[parent.id], operation=f"{node.operation}:{node.quantization or ''}",
            converter_version="llama.cpp" if node.operation == "convert" else None,
            quantizer_version="llama-quantize" if node.operation == "quantize" else None))

    def _register_ollama(self, parent: ModelArtifact, name: str, quant: str, node: BuildNode) -> ModelArtifact:
        art = ModelArtifact(
            logical_model=parent.logical_model, variant_id=f"ollama-{quant.lower().replace('_', '-')}",
            architecture=parent.architecture, parameter_count=parent.parameter_count, format=ModelFormat.OLLAMA,
            quantization=quant, path=f"ollama://{name}", context_length=parent.context_length,
            multimodal=parent.multimodal, runtime_targets=["ollama"],
            size_bytes=0, checksum=f"ollama:{name}", parent_id=parent.id, metadata={"ollama_name": name, "node": node.model_dump()})
        return self.store.add_artifact(art, ModelLineage(artifact_id=art.id, parent_ids=[parent.id],
                                                         operation=f"quantize:{quant}", quantizer_version="ollama"))

    # ================================================================== publish / benchmark / validate
    def _provider_key(self, variant: ModelVariant) -> str:
        providers = self.evaluator.providers
        if variant.runtime == "ollama":
            if "ollama" not in providers:
                providers["ollama"] = OllamaProvider(self.ollama_url)
            return "ollama"
        key = f"{variant.runtime}:{variant.id}"
        if key not in providers and variant.endpoint:
            providers[key] = OpenAICompatibleProvider(variant.endpoint)
        return key

    def temp_profile(self, variant: ModelVariant) -> ModelProfile:
        art = self.store.artifacts[variant.artifact_id]
        profile = profile_for(variant, art, self.eval_reports.get(variant.id))
        profile.provider = self._provider_key(variant)
        return profile

    async def publish(self, artifact_id: str, endpoint: str | None = None,
                      runtime_model: str | None = None) -> ModelVariant:
        art = self.store.artifacts[artifact_id]
        variant = await self.publisher.publish(art, endpoint, runtime_model)
        old = self.store.variants.get(variant.id)
        if old is not None:  # keep measurements of an already-published variant
            variant = old.model_copy(update={"runtime_model": variant.runtime_model, "endpoint": variant.endpoint})
        variant.memory_gb = variant.memory_gb or estimate_memory_gb(art.parameter_count or 0,
                                                                    art.quantization or "F16", 4096)
        return self.store.upsert_variant(variant)

    async def benchmark(self, variant_id: str) -> BenchmarkResult:
        v = self.store.variants[variant_id]
        if v.runtime == "ollama":
            res = await OllamaBenchmark(self.ollama_url).run(v.runtime_model, v.id, v.artifact_id)
        elif v.endpoint:
            res = await OpenAIBenchmark(v.endpoint).run(v.runtime_model or v.id, v.id, v.artifact_id)
        else:
            raise ValueError(f"variant {variant_id} has no runtime to benchmark")
        v.benchmark = res
        v.tokens_per_second = res.tokens_per_second or 0.0
        v.ttft_ms = res.ttft_ms or 0.0
        if res.ram_gb:
            v.memory_gb = res.ram_gb
        self.store.upsert_variant(v)
        await self._event("benchmarked", variant=variant_id, tps=v.tokens_per_second, ttft_ms=v.ttft_ms)
        return res

    async def validate(self, variant_id: str, reference_variant: str | None = None,
                       suites: list[str] | None = None) -> ModelVariant:
        v = self.store.variants[variant_id]
        art = self.store.artifacts[v.artifact_id]
        ref_art = ref_eval = None
        if reference_variant and reference_variant in self.store.variants:
            rv = self.store.variants[reference_variant]
            ref_art = self.store.artifacts[rv.artifact_id]
            ref_eval = self.eval_reports.get(reference_variant)
        work = self.store.dir_for(art.logical_model) / "validation"
        work.mkdir(parents=True, exist_ok=True)
        calib = work / "calibration.txt"
        if not calib.exists():
            calib.write_text(build_calibration_text(), encoding="utf-8")
        report, evals = await self.gate.validate(art, self.temp_profile(v), v.benchmark, ref_art, ref_eval,
                                                 str(calib), work, suites)
        self.eval_reports[v.id] = evals
        v.validation = report
        v.approved = report.approved
        v.coding_score = evals.suites["coding"].score if "coding" in evals.suites else 0.0
        v.reasoning_score = evals.suites["reasoning"].score if "reasoning" in evals.suites else 0.0
        v.quality_score = evals.overall
        self.store.upsert_variant(v)
        await self._event("validated", variant=variant_id, approved=v.approved, reasons=report.reasons)
        return v

    async def evaluate_artifact(self, artifact_id: str, reference_variant: str | None = None,
                                endpoint: str | None = None, suites: list[str] | None = None) -> ModelVariant:
        v = await self.publish(artifact_id, endpoint)
        try:
            await self.benchmark(v.id)
        except Exception as exc:
            log.warning("benchmark failed for %s: %s", v.id, exc)
        return await self.validate(v.id, reference_variant, suites)

    # ================================================================== optimize
    async def optimize(self, logical: str, hardware: HardwareProfile | None = None, quality_min: float = 0.95,
                       target: str | None = None, suites: list[str] | None = None) -> dict[str, Any]:
        """inspect -> candidate builds -> benchmark -> compare quality -> Pareto -> winner."""
        hardware = hardware or detect_local()
        built = await self.build(logical, target=target, hardware=hardware)
        src = self.store.source_of(logical)
        candidates = [src.id] + [a["id"] for a in built["artifacts"]]
        variants: list[ModelVariant] = []
        ref_id = None
        for aid in candidates:
            try:
                v = await self.evaluate_artifact(aid, reference_variant=ref_id, suites=suites)
            except Exception as exc:
                built["notes"].append(f"{aid}: evaluation failed: {exc}")
                continue
            ref_id = ref_id or v.id
            variants.append(v)
        reference_quality = variants[0].quality_score if variants else None
        sel: Selection = choose_winner(variants, quality_min, hardware, reference_quality)
        await self._event("optimized", logical=logical, winner=sel.winner.id if sel.winner else None)
        return {"hardware": hardware.model_dump(), "build": built, "selection": sel.model_dump(mode="json")}

    def resolve(self, logical: str, constraints: ResolveConstraints | dict | None = None) -> ModelVariant | None:
        return self.store.resolve(logical, constraints)

    # ================================================================== registry / canary
    def register(self, variant_id: str, enabled: bool = False) -> ModelProfile:
        v = self.store.variants[variant_id]
        profile = self.temp_profile(v)
        profile.enabled = enabled
        self.registry.add(profile)
        return profile

    async def canary(self, variant_id: str) -> Any:
        """shadow evaluation -> 5% -> 20% -> 100% (automatic rollback on degradation)."""
        v = self.store.variants[variant_id]
        if not v.approved:
            raise ValueError(f"{variant_id} did not pass the quality gate")
        if self.lab is None:
            raise RuntimeError("HYDRA Lab not available")
        profile = self.register(variant_id, enabled=False)
        exp = self.lab.create(f"canary {variant_id}", "model", {"enabled_models": [profile.id]},
                              description=f"Model Factory variant {variant_id}")
        self.lab.start_shadow(exp.id)
        v.status = "canary"
        self.store.upsert_variant(v)
        await self._event("canary", variant=variant_id, experiment=exp.id)
        return exp

    def sync_promotions(self) -> list[str]:
        """Apply Lab outcomes: promoted -> production (enabled), rolled back -> retired (disabled)."""
        changed = []
        if self.lab is None:
            return changed
        for exp in self.lab.experiments.values():
            if exp.kind != "model":
                continue
            for mid in exp.overrides.get("enabled_models", []):
                v = self.store.variants.get(mid)
                if v is None:
                    continue
                if exp.status.value == "promoted" and v.status != "production":
                    v.status = "production"
                    if mid in self.registry.models:
                        self.registry.models[mid].enabled = True
                elif exp.status.value in ("rolled_back", "rejected") and v.status != "retired":
                    v.status = "retired"
                    if mid in self.registry.models:
                        self.registry.models[mid].enabled = False
                else:
                    continue
                self.store.upsert_variant(v)
                changed.append(mid)
        return changed

    # ================================================================== adapters
    def register_adapter(self, spec: AdapterSpec) -> AdapterSpec:
        return self.adapters.register(spec)

    async def publish_adapter(self, logical: str) -> ModelVariant:
        spec = self.adapters.adapters[logical]
        art = ModelArtifact(logical_model=logical, variant_id=f"lora-{spec.adapter_name}", architecture="lora",
                            format=ModelFormat.LORA, path=spec.adapter_path, size_bytes=0,
                            checksum=f"adapter:{spec.adapter_name}", metadata={"base": spec.base_model})
        self.store.add_artifact(art, ModelLineage(artifact_id=art.id, operation="adapter"))
        if spec.runtime == "ollama":
            name = f"hydra-{logical}-{spec.adapter_name}:latest".lower()
            res = await self.ollama_quantizer.create(name, spec.base_model, adapter=spec.adapter_path)
            if not res.ok:
                raise RuntimeError(res.stderr[-400:])
            runtime, model, endpoint = "ollama", name, None
        else:
            runtime, model, endpoint = "vllm", spec.adapter_name, spec.endpoint
        v = ModelVariant(id=f"{logical}:lora-{spec.adapter_name}", logical_model=logical, artifact_id=art.id,
                         format=ModelFormat.LORA, runtime=runtime, runtime_model=model, endpoint=endpoint,
                         base_model=spec.base_model, adapter=spec.adapter_name)
        return self.store.upsert_variant(v)

    # ================================================================== distillation / JIT
    async def distill(self, kind: str, **filters) -> DatasetManifest:
        tasks = await self.telemetry.recent_tasks(100_000) if self.telemetry else []
        if kind == "routing":
            return self.datasets.routing(tasks, filters.get("min_confidence", 0.8))
        if kind == "critic":
            return self.datasets.critic(tasks)
        return self.datasets.specialist(tasks, filters.get("task_type"), filters.get("min_confidence", 0.85),
                                        filters.get("tools"))

    async def train(self, job: TrainingJob, logical: str | None = None) -> dict[str, Any]:
        """LoRA -> merge -> import as a new logical model source (then build/validate/canary)."""
        res = await self.trainer.train(job)
        if not res.ok:
            raise RuntimeError(f"training failed: {res.stderr[-600:]}")
        merged = Path(job.output_dir) / "merged"
        mres = await self.trainer.merge(job.base_model, job.output_dir, str(merged))
        if not mres.ok:
            raise RuntimeError(f"merge failed: {mres.stderr[-600:]}")
        art = await self.import_model(ModelSource(source_type=SourceType.LOCAL_DIR, location=str(merged)),
                                      logical or Path(job.output_dir).name)
        lin = self.store.lineage[art.id]
        lin.dataset_ids.append(job.dataset)
        lin.training_run = job.id
        lin.parent_ids.append(f"base:{job.base_model}")
        self.store.add_artifact(art, lin)
        return {"artifact": art.id, "training_job": job.id}

    async def jit_proposals(self) -> list[SpecialistProposal]:
        if self.telemetry is None:
            return []
        return self.jit.mine(await self.telemetry.recent_tasks(100_000), await self.telemetry.recent_runs())

    async def propose_specialist(self, proposal: SpecialistProposal, base_model: str) -> dict[str, Any]:
        ds = await self.distill("specialist", task_type=proposal.task_type, tools=proposal.tools)
        job = TrainingJob(base_model=base_model, dataset=ds.path,
                          output_dir=str(self.store.dir_for(proposal.name) / "lora"))
        return {"proposal": proposal.model_dump(), "dataset": ds.model_dump(mode="json"),
                "training_job": job.model_dump(), "trainer_available": self.trainer.available(),
                "next": "hydra factory submit train (runs in the factory worker, never in inference)"}

    # ================================================================== jobs
    def submit(self, kind: str, params: dict[str, Any]) -> FactoryJob:
        return self.store.save_job(FactoryJob(kind=kind, params=params))

    async def process(self, job: FactoryJob) -> FactoryJob:
        job.status = JobStatus.RUNNING
        self.store.save_job(job)
        await self._event("job_started", job=job.id, kind=job.kind)
        p = job.params
        try:
            match job.kind:
                case "import":
                    art = await self.import_model(ModelSource.model_validate(p["source"]), p["logical"])
                    job.result = {"artifact": art.model_dump(mode="json")}
                case "build":
                    job.result = await self.build(p["logical"], p.get("target"), _hw(p.get("hardware")),
                                                  p.get("quants"), p.get("formats"))
                case "evaluate":
                    v = await self.evaluate_artifact(p["artifact_id"], p.get("reference"), p.get("endpoint"),
                                                     p.get("suites"))
                    job.result = {"variant": v.model_dump(mode="json")}
                case "optimize":
                    job.result = await self.optimize(p["logical"], _hw(p.get("hardware")),
                                                     p.get("quality_min", 0.95), p.get("target"), p.get("suites"))
                case "canary":
                    exp = await self.canary(p["variant_id"])
                    job.result = {"experiment": exp.id}
                case "distill":
                    ds = await self.distill(p["kind"], **p.get("filters", {}))
                    job.result = {"dataset": ds.model_dump(mode="json")}
                case "train":
                    job.result = await self.train(TrainingJob.model_validate(p["job"]), p.get("logical"))
                case "jit":
                    job.result = {"proposals": [x.model_dump() for x in await self.jit_proposals()]}
                case _:
                    raise ValueError(f"unknown job kind {job.kind}")
            job.status = JobStatus.DONE
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = f"{type(exc).__name__}: {exc}"[:2000]
        job.finished_at = datetime.now(UTC)
        self.store.save_job(job)
        await self._event("job_finished", job=job.id, status=job.status.value)
        return job

    async def run_worker(self, poll_s: float = 2.0, once: bool = False) -> None:
        """Separate process: `hydra factory worker`."""
        while True:
            self.store.reload_jobs()
            queued = sorted((j for j in self.store.jobs.values() if j.status == JobStatus.QUEUED),
                            key=lambda j: j.created_at)
            for job in queued:
                await self.process(job)
            self.sync_promotions()
            if once:
                return
            await asyncio.sleep(poll_s)


def _hw(value: Any) -> HardwareProfile | None:
    if value is None:
        return None
    if isinstance(value, HardwareProfile):
        return value
    if isinstance(value, str):
        return detect_local() if value == "local" else HardwareProfile.from_yaml(value)
    return HardwareProfile.model_validate(value)
