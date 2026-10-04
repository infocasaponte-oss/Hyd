# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Quality gate: a new build never enters production automatically.

load test -> logit sanity (KL divergence vs reference) -> perplexity -> task evals
-> tool calling -> JSON compliance -> latency -> memory usage -> approved?
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from hydra.evals.engine import EvalEngine, EvalReport
from hydra.model_factory.manifest import BenchmarkResult, ModelArtifact, ValidationReport
from hydra.model_factory.runner import CommandRunner, ToolLocator
from hydra.registry.models import ModelProfile

PPL = re.compile(r"Final estimate: PPL = ([0-9.]+)")
KLD = re.compile(r"Mean\s+KLD:\s+([0-9.]+)")
SAME_TOP = re.compile(r"Same top p:\s+([0-9.]+)")


class GateThresholds(BaseModel):
    min_task_score: float = 0.5
    max_task_drop: float = 0.05
    min_structured: float = 0.5
    min_tool_call: float = 0.0
    max_kl_divergence: float = 0.10
    max_perplexity_increase: float = 0.08
    max_memory_gb: float | None = None
    max_ttft_ms: float | None = None


class LogitValidator:
    """llama-perplexity: perplexity and KL divergence against the reference model's logits."""

    def __init__(self, runner: CommandRunner | None = None, tools: ToolLocator | None = None) -> None:
        self.runner = runner or CommandRunner()
        self.tools = tools or ToolLocator()

    def available(self) -> bool:
        return self.tools.binary("llama-perplexity") is not None

    async def perplexity(self, model: str, text_file: str, ctx: int = 512) -> float | None:
        res = await self.runner.run([self.tools.require_binary("llama-perplexity"), "-m", model, "-f", text_file,
                                     "-c", str(ctx), "--chunks", "32"])
        m = PPL.search(res.stdout + res.stderr)
        return float(m.group(1)) if m else None

    async def kl_divergence(self, reference: str, candidate: str, text_file: str, work: Path
                            ) -> tuple[float | None, float | None]:
        base = work / "logits.kld"
        exe = self.tools.require_binary("llama-perplexity")
        await self.runner.run([exe, "-m", reference, "-f", text_file, "--kl-divergence-base", str(base),
                               "--chunks", "32"])
        res = await self.runner.run([exe, "-m", candidate, "--kl-divergence-base", str(base), "--kl-divergence",
                                     "--chunks", "32"])
        out = res.stdout + res.stderr
        kld, top = KLD.search(out), SAME_TOP.search(out)
        return (float(kld.group(1)) if kld else None,
                float(top.group(1)) / (100 if float(top.group(1)) > 1 else 1) if top else None)


class QualityGate:
    def __init__(self, evaluator: EvalEngine, logits: LogitValidator | None = None,
                 thresholds: GateThresholds | None = None) -> None:
        self.evaluator = evaluator
        self.logits = logits or LogitValidator()
        self.t = thresholds or GateThresholds()

    async def validate(
        self,
        artifact: ModelArtifact,
        profile: ModelProfile,
        benchmark: BenchmarkResult | None = None,
        reference: ModelArtifact | None = None,
        reference_eval: EvalReport | None = None,
        calibration_file: str | None = None,
        work_dir: Path | None = None,
        suites: list[str] | None = None,
    ) -> tuple[ValidationReport, EvalReport]:
        reasons: list[str] = []
        requested = suites or ["coding", "reasoning", "structured", "tool_use", "hallucination"]
        report = await self.evaluator.run_model(profile, requested)
        for name in requested:
            if name not in report.suites or report.suites[name].total <= 0:
                reasons.append(f"missing evaluation suite: {name}")
        load_ok = any(not c.detail.startswith("error") for c in report.cases)
        if not load_ok:
            reasons.append("model failed to load / answer")

        v = ValidationReport(
            artifact_id=artifact.id, load_success=load_ok,
            task_score=round(sum(report.suites[s].score for s in ("coding", "reasoning") if s in report.suites)
                             / max(1, sum(1 for s in ("coding", "reasoning") if s in report.suites)), 4),
            structured_output_score=report.suites["structured"].score if "structured" in report.suites else 0.0,
            tool_call_score=report.suites["tool_use"].score if "tool_use" in report.suites else 0.0,
            latency_ms=report.latency_p50_ms,
            memory_gb=benchmark.ram_gb if benchmark else None,
        )

        # logit sanity + perplexity (llama.cpp tooling, GGUF only)
        if (calibration_file and self.logits.available() and artifact.format.value == "gguf"
                and reference is not None and reference.format.value == "gguf" and work_dir is not None):
            v.kl_divergence, v.logits_similarity = await self.logits.kl_divergence(
                reference.path, artifact.path, calibration_file, work_dir)
            v.perplexity = await self.logits.perplexity(artifact.path, calibration_file)
            ref_ppl = await self.logits.perplexity(reference.path, calibration_file)
            if v.perplexity and ref_ppl:
                v.perplexity_delta = round((v.perplexity - ref_ppl) / ref_ppl, 4)

        if v.task_score < self.t.min_task_score:
            reasons.append(f"task score {v.task_score:.2f} < {self.t.min_task_score}")
        if reference_eval is not None:
            task_suites = [s for s in ("coding", "reasoning") if s in report.suites]
            if not task_suites or any(s not in reference_eval.suites for s in task_suites):
                reasons.append("missing comparable reference task suites")
            ref_task = sum(reference_eval.suites[s].score for s in task_suites
                           if s in reference_eval.suites) / max(1, len(task_suites))
            if v.task_score < ref_task - self.t.max_task_drop:
                reasons.append(f"task score dropped {ref_task - v.task_score:.2f} vs reference")
        if v.structured_output_score < self.t.min_structured:
            reasons.append(f"JSON compliance {v.structured_output_score:.2f} < {self.t.min_structured}")
        if v.tool_call_score < self.t.min_tool_call:
            reasons.append(f"tool calling {v.tool_call_score:.2f} < {self.t.min_tool_call}")
        if v.kl_divergence is not None and v.kl_divergence > self.t.max_kl_divergence:
            reasons.append(f"KL divergence {v.kl_divergence:.3f} > {self.t.max_kl_divergence}")
        if v.perplexity_delta is not None and v.perplexity_delta > self.t.max_perplexity_increase:
            reasons.append(f"perplexity +{v.perplexity_delta:.1%}")
        if self.t.max_memory_gb is not None:
            if v.memory_gb is None or v.memory_gb <= 0:
                reasons.append("missing memory measurement")
            elif v.memory_gb > self.t.max_memory_gb:
                reasons.append(f"memory {v.memory_gb} GB > {self.t.max_memory_gb} GB")
        if self.t.max_ttft_ms is not None:
            if benchmark is None or benchmark.ttft_ms is None or benchmark.ttft_ms <= 0:
                reasons.append("missing TTFT measurement")
            elif benchmark.ttft_ms > self.t.max_ttft_ms:
                reasons.append(f"TTFT {benchmark.ttft_ms} ms > {self.t.max_ttft_ms} ms")

        v.reasons = reasons
        v.approved = load_ok and not reasons
        return v, report
