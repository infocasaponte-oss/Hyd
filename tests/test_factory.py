# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from hydra.core.contracts import TaskType
from hydra.lab.lab import ExperimentStatus
from hydra.model_factory.gguf import read_gguf, write_gguf
from hydra.model_factory.hardware import HardwareProfile, detect_local, estimate_memory_gb, preferred_formats
from hydra.model_factory.inspector import inspect
from hydra.model_factory.jit import CognitiveJIT
from hydra.model_factory.manifest import (
    BenchmarkResult,
    JobStatus,
    ModelFormat,
    ModelSource,
    ModelVariant,
    SourceType,
)
from hydra.model_factory.optimizer import choose_winner, pareto_frontier
from hydra.model_factory.quantizer import GGUFQuantizer, QuantizationPlanner, QuantSpec
from hydra.model_factory.runner import CommandResult, ToolLocator
from hydra.model_factory.safetensors import write_safetensors
from hydra.model_factory.service import ModelFactory
from hydra.model_factory.store import FactoryStore
from hydra.model_factory.validator import GateThresholds
from hydra.telemetry.metrics import InferenceRun, TaskRecord

FTYPE = {"BF16": 32, "F16": 1, "Q8_0": 7, "Q6_K": 18, "Q5_K_M": 17, "Q4_K_M": 15, "IQ4_XS": 30, "IQ3_M": 27}


def tiny_gguf(path: Path, ftype: int = 1, arch: str = "llama") -> Path:
    return write_gguf(path, {
        "general.architecture": arch, "general.name": "tiny", "general.file_type": ftype,
        f"{arch}.context_length": 4096, f"{arch}.block_count": 2, f"{arch}.embedding_length": 8,
        "tokenizer.ggml.model": "gpt2", "tokenizer.ggml.tokens": [f"t{i}" for i in range(100)],
        "tokenizer.chat_template": "{{ messages }}",
    }, {"token_embd.weight": [[0.1] * 8 for _ in range(4)], "output_norm.weight": [1.0] * 8})


class FakeRunner:
    """Stands in for llama.cpp / ollama: writes real GGUF outputs."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    async def run(self, cmd, cwd=None, timeout=0, stdin=None) -> CommandResult:
        self.commands.append(cmd)
        joined = " ".join(cmd)
        if "convert_hf_to_gguf.py" in joined:
            tiny_gguf(Path(cmd[cmd.index("--outfile") + 1]), FTYPE["BF16"])
        elif "llama-imatrix" in cmd[0]:
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"imatrix")
        elif "llama-quantize" in cmd[0]:
            quant = cmd[-1]
            tiny_gguf(Path(cmd[-2]), FTYPE[quant])
        return CommandResult(cmd=cmd, returncode=0, stdout="ok", stderr="")


class FakeTools(ToolLocator):
    def binary(self, name):
        return name if name.startswith("llama-") or name == "ollama" else None

    def llamacpp_script(self, name="convert_hf_to_gguf.py"):
        return name


@pytest.fixture
def hf_model(tmp_path) -> Path:
    d = tmp_path / "tiny-llama"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({
        "architectures": ["LlamaForCausalLM"], "torch_dtype": "bfloat16", "max_position_embeddings": 4096,
        "hidden_size": 64, "num_hidden_layers": 2, "vocab_size": 100}))
    (d / "tokenizer_config.json").write_text(json.dumps({"chat_template": "{{ messages }}"}))
    (d / "tokenizer.json").write_text("{}")
    write_safetensors(d / "model.safetensors", {"embed.weight": ("BF16", [100, 64]),
                                                "layers.0.mlp.weight": ("BF16", [64, 64])})
    return d


@pytest.fixture
def factory(runtime, tmp_path) -> ModelFactory:
    runtime.evaluator.providers["ollama"] = runtime.providers["mock"]  # variants are served by the mock
    return ModelFactory(FactoryStore(tmp_path / "factory"), runtime.registry, runtime.evaluator,
                        runtime.telemetry, runtime.bus, runtime.lab, runner=FakeRunner(), tools=FakeTools(),
                        thresholds=GateThresholds(min_task_score=0.3, min_structured=0.0))


# ------------------------------------------------------------------ formats
def test_gguf_roundtrip(tmp_path):
    p = tiny_gguf(tmp_path / "m.gguf", FTYPE["Q4_K_M"])
    g = read_gguf(p)
    assert g.architecture == "llama" and g.file_type == "Q4_K_M" and g.parameters == 32 + 8
    assert g.arch_key("context_length") == 4096
    assert g.metadata["tokenizer.ggml.tokens"]["count"] == 100  # large arrays are skipped, not loaded
    ins = inspect(p)
    assert ins.format == ModelFormat.GGUF and ins.has_chat_template and ins.supports_gguf


def test_inspect_hf_reads_transformers5_dtype_key(hf_model):
    # transformers 5 saves "dtype" in config.json instead of "torch_dtype"
    cfg = json.loads((hf_model / "config.json").read_text())
    cfg["dtype"] = "float16"
    del cfg["torch_dtype"]
    (hf_model / "config.json").write_text(json.dumps(cfg))
    assert inspect(hf_model).dtype == "F16"


def test_inspect_hf_and_lora(hf_model, tmp_path):
    ins = inspect(hf_model)
    assert ins.format == ModelFormat.SAFETENSORS and ins.architecture == "LlamaForCausalLM"
    assert ins.parameters == 100 * 64 + 64 * 64 and ins.dtype == "BF16"
    assert ins.supports_gguf and ins.supports_vllm and ins.supports_mlx and ins.has_chat_template
    lora = tmp_path / "lora"
    lora.mkdir()
    (lora / "adapter_config.json").write_text(json.dumps({"base_model_name_or_path": "qwen-7b", "r": 16}))
    write_safetensors(lora / "adapter_model.safetensors", {"a": ("F16", [16, 64])})
    li = inspect(lora)
    assert li.format == ModelFormat.LORA and li.metadata["base_model"] == "qwen-7b"


def test_quantization_planner_and_command():
    ins = inspect.__globals__["ModelInspection"](format=ModelFormat.SAFETENSORS, architecture="X", dtype="BF16",
                                                 parameters=14_000_000_000, context_length=32768, layers=48,
                                                 embedding_length=5120, is_moe=True)
    planner = QuantizationPlanner()
    assert [s.quant for s in planner.choose(ins, "laptop")] == ["Q4_K_M"]
    moe = planner.choose(ins, "server_cpu")[1]
    assert moe.overrides and moe.output_tensor_type == "Q8_0" and moe.imatrix
    small_gpu = HardwareProfile(name="gpu8", cpu_arch="x86_64", system_ram_gb=32, gpu_type="RTX 3060 Ti",
                                gpu_vram_gb=8)
    assert [s.quant for s in planner.choose(ins, hardware=small_gpu)] == ["IQ3_M"]  # nothing fits: smallest
    seven_b = ins.model_copy(update={"parameters": 7_600_000_000, "layers": 28, "embedding_length": 3584})
    fitting = [s.quant for s in planner.choose(seven_b, hardware=small_gpu)]
    assert fitting and all(estimate_memory_gb(seven_b.parameters, q, 8192, 28, 3584) <= small_gpu.memory_budget_gb
                           for q in fitting)
    cmd = GGUFQuantizer(tools=FakeTools()).command("in.gguf", "out.gguf", moe, "imatrix.dat")
    assert cmd[:3] == ["llama-quantize", "--imatrix", "imatrix.dat"] and "--tensor-type" in cmd
    assert cmd[-1] == "Q4_K_M"
    with pytest.raises(ValueError):
        import asyncio
        asyncio.run(GGUFQuantizer(tools=FakeTools(), runner=FakeRunner()).quantize("a", "b", QuantSpec(quant="IQ3_M")))


def test_hardware_profiles():
    local = detect_local()
    assert local.system_ram_gb > 0
    mac = HardwareProfile(name="mac", cpu_arch="arm64", system_ram_gb=64, apple_silicon=True)
    assert preferred_formats(mac)[0] == ModelFormat.MLX
    cpu = HardwareProfile(name="cpu", cpu_arch="x86_64", system_ram_gb=64)
    assert preferred_formats(cpu)[0] == ModelFormat.GGUF
    rtx = HardwareProfile(name="5090", cpu_arch="x86_64", system_ram_gb=128, gpu_type="RTX 5090", gpu_vram_gb=32)
    assert preferred_formats(rtx)[0] == ModelFormat.FP8


# ------------------------------------------------------------------ pareto / resolver
def _v(id, q, tps, mem, approved=True, fmt=ModelFormat.GGUF) -> ModelVariant:
    return ModelVariant(id=id, logical_model="m", artifact_id=id, format=fmt, quality_score=q,
                        tokens_per_second=tps, memory_gb=mem, approved=approved)


def test_pareto_and_winner():
    vs = [_v("bf16", 1.0, 47, 29), _v("q8", 0.99, 31, 16), _v("q6", 0.97, 30, 13), _v("q5", 0.968, 43, 10),
          _v("q4", 0.947, 49, 8.5), _v("bad", 0.2, 90, 2, approved=False)]
    front = {v.id for v in pareto_frontier([v for v in vs if v.approved])}
    assert "q6" not in front and {"bf16", "q8", "q5", "q4"} <= front
    assert choose_winner(vs, quality_min=0.96).winner.id == "bf16"  # unconstrained: fastest good variant
    cpu24 = HardwareProfile(name="cpu24", cpu_arch="x86_64", system_ram_gb=24)  # budget 14.4 GB
    sel = choose_winner(vs, quality_min=0.96, hardware=cpu24, reference_quality=1.0)
    assert sel.winner.id == "q5" and "q6" in sel.dominated and "bad" in sel.rejected
    laptop = HardwareProfile(name="l", cpu_arch="x86_64", system_ram_gb=16)
    assert choose_winner(vs, quality_min=0.99, hardware=laptop).winner.id in ("q5", "q4")


def test_resolver(tmp_path):
    store = FactoryStore(tmp_path)
    for v in (_v("m:q8", 0.99, 31, 16), _v("m:q5", 0.968, 43, 10), _v("m:fp8", 0.99, 80, 15, fmt=ModelFormat.FP8)):
        store.upsert_variant(v)
    assert store.resolve("m", {"quality": 0.95, "max_memory_gb": 12, "local": True}).id == "m:q5"
    gpu = HardwareProfile(name="h100", cpu_arch="x86_64", system_ram_gb=256, gpu_type="H100", gpu_vram_gb=80)
    assert store.resolve("m", {"hardware": gpu}).id == "m:fp8"
    assert store.resolve("m", {"quality": 0.999}) is None


# ------------------------------------------------------------------ factory pipeline
async def test_build_graph_lineage_and_quality_gate(factory, hf_model):
    src = await factory.import_model(ModelSource(source_type=SourceType.LOCAL_DIR, location=str(hf_model)),
                                     "hydra-tiny")
    assert src.format == ModelFormat.SAFETENSORS and src.fingerprint.chat_template_hash
    again = await factory.import_model(ModelSource(source_type=SourceType.LOCAL_DIR, location=str(hf_model)),
                                       "hydra-tiny")
    assert again.id == src.id  # same fingerprint -> same artifact

    nodes, notes = factory.plan_builds("hydra-tiny", target="balanced")
    ids = [n.id for n in nodes]
    assert ids[0] == "convert-gguf" and "imatrix" in ids and "quant-q4_k_m" in ids and not notes

    result = await factory.build("hydra-tiny", target="balanced")
    quants = {a["quantization"] for a in result["artifacts"]}
    assert {"BF16", "Q8_0", "Q5_K_M", "Q4_K_M"} <= quants
    q4 = next(a for a in result["artifacts"] if a["quantization"] == "Q4_K_M")
    ops = [lin.operation for lin in factory.store.ancestry(q4["id"])]
    assert ops[0].startswith("quantize") and any(o.startswith("convert") for o in ops) and ops[-1].startswith("import")
    imatrix_used = [c for c in factory.runner.commands if "llama-quantize" in c[0] and "--imatrix" in c]
    assert imatrix_used

    v = await factory.publish(q4["id"])
    assert v.runtime == "ollama" and v.runtime_model.startswith("hydra-hydra-tiny")
    assert any(c[:2] == ["ollama", "create"] for c in factory.runner.commands)
    v = await factory.validate(v.id)
    assert v.validation.load_success and v.approved and 0 < v.quality_score <= 1

    profile = factory.register(v.id)
    assert profile.logical_model == "hydra-tiny" and not profile.enabled
    assert runtime_quality(profile) > 0

    exp = await factory.canary(v.id)
    assert exp.status == ExperimentStatus.SHADOW and exp.overrides == {"enabled_models": [v.id]}
    factory.lab.promote(exp.id)
    assert factory.sync_promotions() == [v.id]
    assert factory.store.variants[v.id].status == "production" and factory.registry.get(v.id).enabled


def runtime_quality(profile) -> float:
    return profile.capabilities.for_task(TaskType.CODING)


async def test_quantized_source_is_not_requantized(factory, tmp_path):
    p = tiny_gguf(tmp_path / "q4.gguf", FTYPE["Q4_K_M"])
    await factory.import_model(ModelSource(source_type=SourceType.GGUF_FILE, location=str(p)), "prequant")
    nodes, notes = factory.plan_builds("prequant", target="balanced")
    assert nodes == [] and "already quantized" in notes[0]


async def test_optimize_selects_on_pareto(factory, hf_model, monkeypatch):
    await factory.import_model(ModelSource(source_type=SourceType.LOCAL_DIR, location=str(hf_model)), "opt")
    speeds = {"BF16": (20, 29), "Q8_0": (31, 16), "Q5_K_M": (43, 10), "Q4_K_M": (49, 8.5)}

    async def fake_benchmark(variant_id):
        v = factory.store.variants[variant_id]
        tps, mem = speeds.get(v.quantization or "BF16", (10, 30))
        v.tokens_per_second, v.memory_gb = tps, mem
        v.benchmark = BenchmarkResult(artifact_id=v.artifact_id, variant_id=v.id, tokens_per_second=tps, ram_gb=mem)
        factory.store.upsert_variant(v)
        return v.benchmark

    monkeypatch.setattr(factory, "benchmark", fake_benchmark)
    hw = HardwareProfile(name="cpu64", cpu_arch="x86_64", system_ram_gb=64)
    out = await factory.optimize("opt", hardware=hw, quality_min=0.9, target="balanced", suites=["coding"])
    sel = out["selection"]
    assert sel["winner"] is not None and sel["winner"]["quantization"] == "Q4_K_M"
    assert factory.resolve("opt", {"hardware": hw}) is not None


async def test_distillation_jit_and_jobs(factory, runtime):
    tasks, runs = [], []
    for i in range(60):
        tid = uuid4()
        tasks.append(TaskRecord(
            id=tid, status="completed",
            request={"messages": [{"role": "user", "content": f"python bug {i}"}]},
            route={"task_type": "coding", "complexity": 0.6, "risk": 0.1, "requires_tools": True},
            final_response={"answer": f"fixed {i}", "uncertainties": [],
                            "meta": {"task_type": "coding", "confidence": 0.9, "verified": True,
                                     "tools_used": ["python.execute"], "latency_ms": 900, "decision": "answer"}}))
        runs += [InferenceRun(task_id=tid, task_type="coding", model_id="large", role=r, latency_ms=300)
                 for r in ("coder", "coder", "critic", "judge")]
    for t in tasks:
        await runtime.telemetry.save_task(t)
    await runtime.telemetry.record_runs(runs)

    ds = await factory.distill("routing")
    lines = Path(ds.path).read_text(encoding="utf-8").splitlines()
    assert ds.examples == 60 and json.loads(json.loads(lines[0])["messages"][-1]["content"])["task_type"] == "coding"
    crit = await factory.distill("critic")
    assert crit.examples == 60

    proposals = await factory.jit_proposals()
    assert proposals and proposals[0].task_type == "coding" and proposals[0].mean_model_calls == 4
    plan = await factory.propose_specialist(proposals[0], base_model="Qwen/Qwen2.5-1.5B-Instruct")
    assert plan["dataset"]["examples"] == 60 and plan["training_job"]["method"] == "lora"

    job = factory.submit("jit", {})
    await factory.run_worker(once=True)
    assert factory.store.jobs[job.id].status == JobStatus.DONE
    bad = factory.submit("nonsense", {})
    await factory.run_worker(once=True)
    assert factory.store.jobs[bad.id].status == JobStatus.FAILED


def test_jit_ignores_rare_or_cheap_patterns():
    t = TaskRecord(id=uuid4(), status="completed", request={}, created_at=datetime.now(UTC),
                   final_response={"answer": "x", "meta": {"task_type": "chat", "confidence": 0.95}})
    assert CognitiveJIT(min_examples=2).mine([t], []) == []
