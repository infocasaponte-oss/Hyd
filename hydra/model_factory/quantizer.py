# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Quantization: planner (which variants to build) + GGUF quantizer (llama-quantize, with
imatrix and per-tensor precision) + Ollama quantizer (ollama create --quantize)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from hydra.model_factory.hardware import HardwareProfile, estimate_memory_gb
from hydra.model_factory.manifest import ModelInspection
from hydra.model_factory.runner import CommandResult, CommandRunner, ToolLocator

GGUF_QUANTS = ("Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "IQ4_XS", "IQ3_M")
IMATRIX_REQUIRED = {"IQ3_M", "IQ3_XXS", "IQ2_M", "IQ2_XS", "IQ2_XXS", "IQ1_S", "IQ1_M"}
IMATRIX_RECOMMENDED = {"IQ4_XS", "Q4_K_M", "Q4_K_S", "Q3_K_M", "Q3_K_S", "Q2_K"}

TARGETS: dict[str, list[str]] = {
    "server_cpu": ["Q5_K_M", "Q4_K_M"],
    "high_quality_local": ["Q8_0", "Q6_K"],
    "laptop": ["Q4_K_M"],
    "edge": ["IQ4_XS", "IQ3_M"],
    "balanced": ["Q8_0", "Q5_K_M", "Q4_K_M"],
}


class TensorOverride(BaseModel):
    """Per-tensor precision: e.g. attention in Q5, experts in Q4, embeddings/output in Q8."""

    pattern: str
    type: str


class QuantSpec(BaseModel):
    quant: str
    imatrix: bool = False
    overrides: list[TensorOverride] = Field(default_factory=list)
    output_tensor_type: str | None = None
    token_embedding_type: str | None = None
    estimated_memory_gb: float | None = None


class QuantizationPlanner:
    def choose(self, inspection: ModelInspection, target: str | None = None,
               hardware: HardwareProfile | None = None) -> list[QuantSpec]:
        if target and target in TARGETS:
            quants = list(TARGETS[target])
        elif hardware is not None:
            quants = self._for_hardware(inspection, hardware)
        else:
            quants = list(TARGETS["balanced"])
        specs = []
        for q in quants:
            spec = QuantSpec(quant=q, imatrix=q in IMATRIX_REQUIRED or q in IMATRIX_RECOMMENDED,
                             estimated_memory_gb=estimate_memory_gb(
                                 inspection.parameters, q, min(inspection.context_length or 8192, 8192),
                                 inspection.layers, inspection.embedding_length))
            if inspection.is_moe:
                # MoE: experts dominate size and tolerate low bits; keep attention/shared layers higher.
                spec.overrides = [TensorOverride(pattern="attn", type="Q6_K" if q.startswith(("Q4", "IQ")) else q),
                                  TensorOverride(pattern="ffn_.*_exps", type=q)]
            if q.startswith(("Q4", "Q3", "IQ", "Q2")):
                spec.output_tensor_type = "Q8_0"
                spec.token_embedding_type = "Q8_0"
            specs.append(spec)
        return specs

    @staticmethod
    def _for_hardware(inspection: ModelInspection, hw: HardwareProfile) -> list[str]:
        budget = hw.memory_budget_gb
        ctx = min(inspection.context_length or 8192, 8192)
        fitting = [q for q in GGUF_QUANTS
                   if estimate_memory_gb(inspection.parameters, q, ctx, inspection.layers,
                                         inspection.embedding_length) <= budget]
        return fitting[:2] or ["IQ3_M"]


class GGUFQuantizer:
    def __init__(self, runner: CommandRunner | None = None, tools: ToolLocator | None = None) -> None:
        self.runner = runner or CommandRunner()
        self.tools = tools or ToolLocator()

    def command(self, input_path: str, output_path: str, spec: QuantSpec, imatrix_path: str | None = None,
                threads: int | None = None) -> list[str]:
        cmd = [self.tools.require_binary("llama-quantize")]
        if imatrix_path:
            cmd += ["--imatrix", imatrix_path]
        if spec.output_tensor_type:
            cmd += ["--output-tensor-type", spec.output_tensor_type.lower()]
        if spec.token_embedding_type:
            cmd += ["--token-embedding-type", spec.token_embedding_type.lower()]
        for o in spec.overrides:
            cmd += ["--tensor-type", f"{o.pattern}={o.type.lower()}"]
        cmd += [input_path, output_path, spec.quant]
        if threads:
            cmd.append(str(threads))
        return cmd

    async def quantize(self, input_path: str, output_path: str, spec: QuantSpec,
                       imatrix_path: str | None = None) -> CommandResult:
        if spec.quant in IMATRIX_REQUIRED and not imatrix_path:
            raise ValueError(f"{spec.quant} requires an importance matrix")
        return await self.runner.run(self.command(input_path, output_path, spec, imatrix_path))


class OllamaQuantizer:
    """Quantize through Ollama (F16/F32/BF16 sources only) and publish in one step."""

    def __init__(self, runner: CommandRunner | None = None, tools: ToolLocator | None = None) -> None:
        self.runner = runner or CommandRunner()
        self.tools = tools or ToolLocator()

    async def create(self, name: str, source: str, quant: str | None = None, template: str | None = None,
                     system: str | None = None, parameters: dict | None = None,
                     adapter: str | None = None) -> CommandResult:
        lines = [f"FROM {source}"]
        if adapter:
            lines.append(f"ADAPTER {adapter}")
        if template:
            lines.append(f'TEMPLATE """{template}"""')
        if system:
            lines.append(f'SYSTEM """{system}"""')
        for k, v in (parameters or {}).items():
            lines.append(f"PARAMETER {k} {v}")
        with tempfile.TemporaryDirectory(prefix="hydra-modelfile-") as tmp:
            mf = Path(tmp) / "Modelfile"
            mf.write_text("\n".join(lines) + "\n", encoding="utf-8")
            cmd = [self.tools.binary("ollama") or "ollama", "create", name, "-f", str(mf)]
            if quant:
                cmd += ["--quantize", quant.lower() if quant.upper().startswith("Q") else quant]
            return await self.runner.run(cmd, timeout=6 * 3600)
