# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Format converters. Each wraps the official tool of its ecosystem and reports clearly
when that tool is not installed - HYDRA never pretends a conversion happened."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from hydra.model_factory.manifest import ModelFormat, ModelInspection
from hydra.model_factory.runner import CommandResult, CommandRunner, ToolLocator, ToolMissing


class Converter(ABC):
    target: ModelFormat

    def __init__(self, runner: CommandRunner | None = None, tools: ToolLocator | None = None) -> None:
        self.runner = runner or CommandRunner()
        self.tools = tools or ToolLocator()

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def supports(self, inspection: ModelInspection) -> bool: ...

    @abstractmethod
    def command(self, src: Path, out: Path, **params) -> list[str]: ...

    def output_path(self, out_dir: Path, name: str, **params) -> Path:
        return out_dir / name

    async def convert(self, src: Path, out_dir: Path, name: str, **params) -> tuple[Path, CommandResult]:
        if not self.available():
            raise ToolMissing(f"converter for {self.target.value} is not installed")
        out = self.output_path(out_dir, name, **params)
        out.parent.mkdir(parents=True, exist_ok=True)
        res = await self.runner.run(self.command(src, out, **params))
        return out, res


class HFToGGUF(Converter):
    """safetensors -> GGUF (F16/BF16/Q8_0) with llama.cpp's convert_hf_to_gguf.py."""

    target = ModelFormat.GGUF

    def available(self) -> bool:
        return self.tools.llamacpp_script() is not None

    def supports(self, inspection: ModelInspection) -> bool:
        return inspection.supports_gguf

    def output_path(self, out_dir: Path, name: str, outtype: str = "bf16", **_) -> Path:
        return out_dir / f"{name}-{outtype}.gguf"

    def command(self, src: Path, out: Path, outtype: str = "bf16", **_) -> list[str]:
        script = self.tools.llamacpp_script()
        if script is None:
            raise ToolMissing("convert_hf_to_gguf.py not found (set HYDRA_LLAMACPP_DIR)")
        return [self.tools.python(), script, str(src), "--outfile", str(out), "--outtype", outtype]


class LoRAToGGUF(Converter):
    target = ModelFormat.GGUF

    def available(self) -> bool:
        return self.tools.llamacpp_script("convert_lora_to_gguf.py") is not None

    def supports(self, inspection: ModelInspection) -> bool:
        return inspection.format == ModelFormat.LORA

    def output_path(self, out_dir: Path, name: str, **_) -> Path:
        return out_dir / f"{name}-lora.gguf"

    def command(self, src: Path, out: Path, base: str | None = None, **_) -> list[str]:
        cmd = [self.tools.python(), self.tools.llamacpp_script("convert_lora_to_gguf.py"), str(src),
               "--outfile", str(out)]
        if base:
            cmd += ["--base", base]
        return cmd


class ToMLX(Converter):
    target = ModelFormat.MLX

    def available(self) -> bool:
        return self.tools.python_module("mlx_lm")

    def supports(self, inspection: ModelInspection) -> bool:
        return inspection.supports_mlx

    def output_path(self, out_dir: Path, name: str, bits: int = 4, **_) -> Path:
        return out_dir / f"{name}-mlx-{bits}bit"

    def command(self, src: Path, out: Path, bits: int = 4, **_) -> list[str]:
        return [self.tools.python(), "-m", "mlx_lm", "convert", "--hf-path", str(src), "--mlx-path", str(out),
                "-q", "--q-bits", str(bits)]


class ToONNX(Converter):
    target = ModelFormat.ONNX

    def available(self) -> bool:
        return self.tools.python_module("optimum")

    def supports(self, inspection: ModelInspection) -> bool:
        return inspection.format == ModelFormat.SAFETENSORS

    def output_path(self, out_dir: Path, name: str, **_) -> Path:
        return out_dir / f"{name}-onnx"

    def command(self, src: Path, out: Path, task: str = "text-generation-with-past", **_) -> list[str]:
        return [self.tools.python(), "-m", "optimum.exporters.onnx", "--model", str(src), "--task", task, str(out)]


_LLMCOMPRESSOR = """
import sys
from llmcompressor import oneshot
from llmcompressor.modifiers.quantization import QuantizationModifier, GPTQModifier
from llmcompressor.modifiers.awq import AWQModifier
src, out, scheme, calib = sys.argv[1:5]
if scheme == "fp8":
    recipe = QuantizationModifier(targets="Linear", scheme="FP8_DYNAMIC", ignore=["lm_head"])
    oneshot(model=src, recipe=recipe, output_dir=out)
else:
    Mod = AWQModifier if scheme == "awq" else GPTQModifier
    recipe = Mod(targets="Linear", scheme="W4A16", ignore=["lm_head"])
    oneshot(model=src, dataset=calib if calib != "-" else "open_platypus", recipe=recipe, output_dir=out,
            max_seq_length=2048, num_calibration_samples=256)
"""


class LLMCompressorConverter(Converter):
    """AWQ / GPTQ / FP8 checkpoints for vLLM through llm-compressor."""

    def __init__(self, scheme: str, **kw) -> None:
        super().__init__(**kw)
        self.scheme = scheme
        self.target = {"awq": ModelFormat.AWQ, "gptq": ModelFormat.GPTQ, "fp8": ModelFormat.FP8}[scheme]

    def available(self) -> bool:
        return self.tools.python_module("llmcompressor")

    def supports(self, inspection: ModelInspection) -> bool:
        return inspection.supports_vllm and inspection.format == ModelFormat.SAFETENSORS

    def output_path(self, out_dir: Path, name: str, **_) -> Path:
        return out_dir / f"{name}-{self.scheme}"

    def command(self, src: Path, out: Path, calibration: str | None = None, **_) -> list[str]:
        return [self.tools.python(), "-c", _LLMCOMPRESSOR, str(src), str(out), self.scheme, calibration or "-"]


def converters(runner: CommandRunner | None = None, tools: ToolLocator | None = None) -> dict[str, Converter]:
    kw = {"runner": runner, "tools": tools}
    return {
        "gguf": HFToGGUF(**kw), "lora_gguf": LoRAToGGUF(**kw), "mlx": ToMLX(**kw), "onnx": ToONNX(**kw),
        "awq": LLMCompressorConverter("awq", **kw), "gptq": LLMCompressorConverter("gptq", **kw),
        "fp8": LLMCompressorConverter("fp8", **kw),
    }
