# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Hardware profiles for the local engine (HYDRA-3060Ti and friends).

The RTX 3060 Ti has 8 GB VRAM and is Ampere (CUDA architecture 86): one 7-8B dense
model in GGUF Q4_K_M with an 8K context and a Q8_0 KV cache, parallel 1, leaving
headroom for KV + CUDA runtime instead of filling the 8 GB with weights. The same
resolver recognises other GPUs/Apple/CPU so nothing is hard-coded to one card."""

from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hydra.core.atomic import write_text_atomic

CUDA_ARCH = [  # (substring in GPU name, compute arch)
    ("rtx 50", "120"), ("b200", "100"), ("h100", "90"), ("h200", "90"), ("gh200", "90"), ("l40", "89"),
    ("rtx 40", "89"), ("rtx 4", "89"), ("l4", "89"), ("ada", "89"), ("a100", "80"), ("a30", "80"),
    ("rtx 30", "86"), ("rtx a", "86"), ("a10", "86"), ("a40", "86"), ("rtx 3", "86"), ("rtx 20", "75"),
    ("t4", "75"), ("gtx 16", "75"), ("v100", "70"), ("gtx 10", "61"),
]


class HardwareProfile(BaseModel):
    gpu_name: str
    vram_mb: int
    profile: str
    quant: str
    context: int
    parallel: int
    kv_k: str
    kv_v: str
    runtime: str = "llama.cpp"
    cuda_arch: str | None = None
    max_recommended_model_class: str = ""
    gpu_layers: int = 99

    @property
    def vram_gb(self) -> float:
        return round(self.vram_mb / 1024, 2)

    def as_dict(self) -> dict[str, Any]:
        return {**self.model_dump(), "vram_gb": self.vram_gb}


def cuda_arch(gpu_name: str) -> str | None:
    n = gpu_name.lower()
    return next((arch for key, arch in CUDA_ARCH if key in n), None)


def resolve_profile(gpu_name: str, vram_mb: int) -> HardwareProfile:
    name = gpu_name.lower()
    gb = vram_mb / 1024
    arch = cuda_arch(gpu_name)
    if "3060 ti" in name and gb >= 7.5:
        return HardwareProfile(gpu_name=gpu_name, vram_mb=vram_mb, profile="rtx3060ti", quant="Q4_K_M", context=8192,
                               parallel=1, kv_k="q8_0", kv_v="q8_0", cuda_arch=arch or "86",
                               max_recommended_model_class="7B/8B dense Q4")
    if "apple" in name or "m1" in name or "m2" in name or "m3" in name or "m4" in name:
        return HardwareProfile(gpu_name=gpu_name, vram_mb=vram_mb, profile="apple_silicon", quant="Q5_K_M",
                               context=16384, parallel=2, kv_k="q8_0", kv_v="q8_0", runtime="mlx",
                               max_recommended_model_class=f"{int(gb * 0.7 // 1.2)}B MLX4/GGUF Q5")
    if gb >= 70:
        return HardwareProfile(gpu_name=gpu_name, vram_mb=vram_mb, profile="datacenter_80gb", quant="FP8",
                               context=65536, parallel=16, kv_k="f16", kv_v="f16", runtime="vllm", cuda_arch=arch,
                               max_recommended_model_class="70B FP8 / 32B BF16")
    if gb >= 30:
        return HardwareProfile(gpu_name=gpu_name, vram_mb=vram_mb, profile="nvidia_32gb_class", quant="Q6_K",
                               context=32768, parallel=4, kv_k="q8_0", kv_v="q8_0", cuda_arch=arch,
                               max_recommended_model_class="32B Q4 / 14B Q8")
    if gb >= 20:
        return HardwareProfile(gpu_name=gpu_name, vram_mb=vram_mb, profile="nvidia_24gb_class", quant="Q5_K_M",
                               context=32768, parallel=2, kv_k="q8_0", kv_v="q8_0", cuda_arch=arch,
                               max_recommended_model_class="32B Q4 / 14B Q6")
    if gb >= 11:
        return HardwareProfile(gpu_name=gpu_name, vram_mb=vram_mb, profile="nvidia_12gb_class", quant="Q5_K_M",
                               context=16384, parallel=1, kv_k="q8_0", kv_v="q8_0", cuda_arch=arch,
                               max_recommended_model_class="14B Q4 / 8B Q6")
    if gb >= 5:
        return HardwareProfile(gpu_name=gpu_name, vram_mb=vram_mb, profile="nvidia_low_vram", quant="Q4_K_M",
                               context=4096, parallel=1, kv_k="q8_0", kv_v="q8_0", cuda_arch=arch,
                               max_recommended_model_class="7B Q4 (partial offload) / 3-4B Q5")
    if vram_mb > 0:  # a 4 GB GPU still fully offloads 1-3B Q4 models (HYDRA-SO semantics)
        return HardwareProfile(gpu_name=gpu_name, vram_mb=vram_mb, profile="nvidia_low_vram", quant="Q4_K_M",
                               context=4096, parallel=1, kv_k="q8_0", kv_v="q8_0", cuda_arch=arch,
                               max_recommended_model_class="1-3B Q4 (full offload)")
    return HardwareProfile(gpu_name=gpu_name or "cpu", vram_mb=vram_mb, profile="cpu_only", quant="Q4_K_M",
                           context=4096, parallel=1, kv_k="q8_0", kv_v="q8_0", gpu_layers=0,
                           max_recommended_model_class="1-3B Q4 on CPU")


def detect_nvidia() -> tuple[str, int] | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    name, memory = [x.strip() for x in out[0].split(",", 1)]
    return name, int(float(memory))


def detect_profile() -> HardwareProfile:
    nv = detect_nvidia()
    if nv:
        return resolve_profile(*nv)
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        from hydra.model_factory.hardware import _ram_gb

        return resolve_profile("Apple Silicon", int(_ram_gb() * 1024))
    return resolve_profile("cpu", 0)


def write_hardware_manifest(path: Path) -> dict[str, Any]:
    p = detect_profile().as_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, json.dumps(p, indent=2))
    return p


def llamacpp_cmake_args(profile: HardwareProfile) -> list[str]:
    """CMake flags to build llama.cpp for this machine (e.g. -DCMAKE_CUDA_ARCHITECTURES=86 on a 3060 Ti)."""
    if profile.runtime == "mlx" or profile.profile == "apple_silicon":
        return ["-DGGML_METAL=ON", "-DCMAKE_BUILD_TYPE=Release"]
    if profile.cuda_arch:
        return ["-DGGML_CUDA=ON", f"-DCMAKE_CUDA_ARCHITECTURES={profile.cuda_arch}", "-DCMAKE_BUILD_TYPE=Release"]
    return ["-DCMAKE_BUILD_TYPE=Release"]


def llama_server_args(profile: HardwareProfile, model_path: str, port: int = 8081, ctx: int | None = None,
                      kv_k: str | None = None, kv_v: str | None = None, gpu_layers: int | None = None) -> list[str]:
    return ["-m", model_path, "-ngl", str(profile.gpu_layers if gpu_layers is None else gpu_layers),
            "-c", str(ctx or profile.context), "-np", str(profile.parallel), "-ctk", kv_k or profile.kv_k,
            "-ctv", kv_v or profile.kv_v, "-fa", "on", "--host", "127.0.0.1", "--port", str(port)]
