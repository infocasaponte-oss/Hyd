# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Deployment profiles and the artifact compatibility matrix.

RTX 5090 -> AWQ / FP8 / BF16      Mac Studio -> MLX      CPU 64 GB -> GGUF      laptop 16 GB -> GGUF Q4
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
from pathlib import Path

import yaml
from pydantic import BaseModel

from hydra.model_factory.manifest import ModelFormat


class HardwareProfile(BaseModel):
    name: str
    cpu_arch: str
    system_ram_gb: float
    gpu_type: str | None = None
    gpu_vram_gb: float | None = None
    gpu_count: int = 0
    apple_silicon: bool = False
    target_latency_ms: int | None = None
    os: str = ""

    @classmethod
    def from_yaml(cls, path: str | Path) -> HardwareProfile:
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    @property
    def memory_budget_gb(self) -> float:
        """Memory usable for weights + KV cache on the preferred device."""
        if self.gpu_vram_gb and not self.apple_silicon:
            return self.gpu_vram_gb * 0.85 * max(1, self.gpu_count)
        return self.system_ram_gb * (0.7 if self.apple_silicon else 0.6)


# format -> (primary runtime, scenario)
COMPATIBILITY_MATRIX: dict[ModelFormat, tuple[str, str]] = {
    ModelFormat.GGUF: ("llama.cpp / Ollama", "CPU, edge, local, partial GPU offload"),
    ModelFormat.SAFETENSORS: ("Transformers / vLLM", "training, full-precision GPU serving"),
    ModelFormat.FP8: ("vLLM", "high-throughput serving on Ada/Hopper/Blackwell GPUs"),
    ModelFormat.AWQ: ("vLLM / TGI", "4-bit GPU serving with little VRAM"),
    ModelFormat.GPTQ: ("vLLM / ExLlama", "4-bit GPU serving"),
    ModelFormat.MLX: ("MLX / mlx-lm", "Apple Silicon"),
    ModelFormat.ONNX: ("ONNX Runtime", "edge devices and integrations"),
}

FP8_GPUS = ("H100", "H200", "B100", "B200", "L4", "L40", "RTX 40", "RTX 50", "4090", "4080", "5090", "5080", "ADA")


def preferred_formats(hw: HardwareProfile) -> list[ModelFormat]:
    if hw.apple_silicon:
        return [ModelFormat.MLX, ModelFormat.GGUF]
    if hw.gpu_vram_gb and hw.gpu_vram_gb >= 6:
        gpu = (hw.gpu_type or "").upper()
        fmts = []
        if any(k in gpu for k in FP8_GPUS):
            fmts.append(ModelFormat.FP8)
        fmts += [ModelFormat.AWQ, ModelFormat.GPTQ, ModelFormat.GGUF]
        if hw.gpu_vram_gb >= 40:
            fmts.insert(0, ModelFormat.SAFETENSORS)
        return fmts
    return [ModelFormat.GGUF, ModelFormat.ONNX]


def _ram_gb() -> float:
    try:
        if os.name == "nt":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / 1024 ** 3
        if platform.system() == "Darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip()) / 1024 ** 3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except Exception:
        return 0.0


def detect_local(name: str = "local") -> HardwareProfile:
    arch = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(platform.machine().lower(),
                                                                       platform.machine().lower())
    apple = platform.system() == "Darwin" and arch in ("arm64", "aarch64")
    gpu_type = None
    vram = None
    count = 0
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
            if out:
                count = len(out)
                gpu_type = out[0].split(",")[0].strip()
                vram = round(float(out[0].split(",")[1]) / 1024, 2)
        except Exception:
            pass
    return HardwareProfile(name=name, cpu_arch="arm64" if arch in ("arm64", "aarch64") else arch,
                           system_ram_gb=round(_ram_gb(), 1), gpu_type=gpu_type, gpu_vram_gb=vram,
                           gpu_count=count, apple_silicon=apple, os=platform.system())


# Approximate bits per weight of llama.cpp quantization types (for memory estimates).
BITS_PER_WEIGHT = {
    "F32": 32, "F16": 16, "BF16": 16, "Q8_0": 8.5, "Q6_K": 6.56, "Q5_K_M": 5.69, "Q5_K_S": 5.54, "Q5_0": 5.5,
    "Q4_K_M": 4.85, "Q4_K_S": 4.58, "Q4_0": 4.55, "IQ4_XS": 4.25, "IQ4_NL": 4.5, "Q3_K_L": 4.27,
    "Q3_K_M": 3.91, "Q3_K_S": 3.5, "IQ3_M": 3.66, "IQ3_XXS": 3.06, "Q2_K": 3.35, "IQ2_M": 2.7, "IQ2_XS": 2.31,
    "AWQ": 4.25, "GPTQ": 4.25, "FP8": 8.1, "MLX4": 4.5, "MLX8": 8.5,
}


def estimate_memory_gb(parameters: int, quantization: str, context: int = 8192, layers: int | None = None,
                       embedding: int | None = None) -> float:
    bits = BITS_PER_WEIGHT.get(quantization.upper(), 16)
    weights = parameters * bits / 8 / 1024 ** 3
    kv = 0.0
    if layers and embedding:
        kv = 2 * layers * context * embedding * 2 / 1024 ** 3 / 4  # fp16 KV, GQA ~4x
    return round(weights * 1.05 + kv + 0.3, 2)
