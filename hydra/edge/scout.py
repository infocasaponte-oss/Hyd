# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Model Scout + Model Residency Manager for single-GPU workstations.

Scout: inspect every GGUF on disk and every Ollama model, estimate VRAM (weights + KV at the
profile context), and pick the best model that fits the machine.

Residency: keep exactly ONE large model on the 8 GB GPU; pin small specialists (router,
language detection, embeddings) to CPU/RAM (``num_gpu: 0``); unload idle large models to
avoid swap thrash when a different large model is needed."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from hydra.edge.profiles import HardwareProfile
from hydra.model_factory.hardware import estimate_memory_gb


class ScoutedModel(BaseModel):
    source: str  # gguf | ollama
    name: str
    path: str | None = None
    architecture: str | None = None
    parameters: int | None = None
    quantization: str | None = None
    context_length: int | None = None
    size_gb: float | None = None
    estimated_vram_gb: float | None = None
    fits_gpu: bool = False
    fits_cpu: bool = True
    score: float = 0.0
    families: list[str] = Field(default_factory=list)


def _params(text: str | None) -> int | None:
    if not text:
        return None
    m = re.match(r"([\d.]+)\s*([BM])", str(text).upper())
    if not m:
        return None
    return int(float(m.group(1)) * (1e9 if m.group(2) == "B" else 1e6))


def _quality_proxy(params: int | None, quant: str | None) -> float:
    if not params:
        return 0.0
    q = (quant or "Q4_K_M").upper()
    bits = {"Q8": 1.0, "Q6": 0.99, "Q5": 0.98, "Q4": 0.96, "IQ4": 0.955, "Q3": 0.92, "IQ3": 0.9, "Q2": 0.85,
            "F16": 1.0, "BF16": 1.0}
    factor = next((v for k, v in bits.items() if q.startswith(k)), 0.95)
    import math

    return round(math.log10(params / 1e8) * factor, 4)


def scan_gguf(dirs: list[Path], profile: HardwareProfile, headroom_gb: float = 1.0) -> list[ScoutedModel]:
    from hydra.model_factory.inspector import inspect

    out = []
    for d in dirs:
        for p in sorted(d.rglob("*.gguf")) if d.exists() else []:
            try:
                ins = inspect(p)
            except Exception:
                continue
            vram = estimate_memory_gb(ins.parameters, ins.quantization or "Q4_K_M",
                                      min(profile.context, ins.context_length or profile.context), ins.layers,
                                      ins.embedding_length)
            out.append(ScoutedModel(source="gguf", name=p.stem, path=str(p), architecture=ins.architecture,
                                    parameters=ins.parameters, quantization=ins.quantization,
                                    context_length=ins.context_length, size_gb=round(p.stat().st_size / 2**30, 2),
                                    estimated_vram_gb=round(vram, 2), fits_gpu=vram + headroom_gb <= profile.vram_gb,
                                    score=_quality_proxy(ins.parameters, ins.quantization)))
    return out


def scan_ollama(base_url: str, profile: HardwareProfile, headroom_gb: float = 1.0) -> list[ScoutedModel]:
    out = []
    try:
        tags = httpx.get(f"{base_url}/api/tags", timeout=5).json().get("models", [])
    except Exception:
        return out
    for t in tags:
        det = t.get("details", {})
        params = _params(det.get("parameter_size"))
        quant = det.get("quantization_level")
        ctx = None
        try:
            show = httpx.post(f"{base_url}/api/show", json={"model": t["name"]}, timeout=10).json()
            info = show.get("model_info", {})
            ctx = next((v for k, v in info.items() if k.endswith(".context_length")), None)
        except Exception:
            pass
        size_gb = t.get("size", 0) / 2**30
        kv = estimate_memory_gb(params or 1, "F16", min(profile.context, ctx or profile.context)) - \
            estimate_memory_gb(params or 1, "F16", 0) if params else 0.5
        vram = size_gb + max(0.3, kv * 0.5)
        fam = det.get("families") or [det.get("family")] if det.get("family") else []
        out.append(ScoutedModel(source="ollama", name=t["name"], architecture=det.get("family"), parameters=params,
                                quantization=quant, context_length=ctx, size_gb=round(size_gb, 2),
                                estimated_vram_gb=round(vram, 2), fits_gpu=vram + headroom_gb <= profile.vram_gb,
                                score=_quality_proxy(params, quant), families=[f for f in fam if f]))
    return out


def best_fit(models: list[ScoutedModel], exclude: tuple[str, ...] = ("embed", "bert", "nomic")) -> dict[str, Any]:
    gen = [m for m in models if not any(x in (m.name + " " + " ".join(m.families)).lower() for x in exclude)]
    gpu = sorted((m for m in gen if m.fits_gpu), key=lambda m: -m.score)
    small = sorted((m for m in gen if (m.parameters or 1e12) <= 3.5e9), key=lambda m: -m.score)
    return {"main": gpu[0].model_dump() if gpu else None,
            "cpu_specialists": [m.model_dump() for m in small[:3]],
            "rejected_too_big": [m.name for m in gen if not m.fits_gpu]}


# ------------------------------------------------------------------------------ residency
class ResidencyPlan(BaseModel):
    gpu_main: str | None
    cpu_pinned: list[str] = Field(default_factory=list)
    unload: list[str] = Field(default_factory=list)
    reason: str = ""


class ResidencyManager:
    def __init__(self, registry, ollama_url: str = "http://localhost:11434", vram_gb: float = 8.0,
                 small_params: float = 3.5e9) -> None:
        self.registry = registry
        self.url = ollama_url
        self.vram_gb = vram_gb
        self.small_params = small_params

    def _is_small(self, m) -> bool:
        p = _params(re.search(r"(\d+(?:\.\d+)?[bm])\b", m.physical_name.lower()).group(1)
                    if re.search(r"(\d+(?:\.\d+)?[bm])\b", m.physical_name.lower()) else None)
        return (p or 1e12) <= self.small_params or m.tier <= 1

    def plan(self, loaded: list[dict[str, Any]], wanted: str) -> ResidencyPlan:
        """Before invoking ``wanted``: keep it (and only it) as the large GPU model."""
        m = self.registry.models.get(wanted)
        name = m.physical_name if m else wanted
        big_loaded = [x["name"] for x in loaded if x.get("size_vram", 0) > 0
                      and not any(self._is_small(r) for r in self.registry.all() if r.physical_name == x["name"])]
        unload = [n for n in big_loaded if n != name]
        cpu = [r.physical_name for r in self.registry.all() if r.provider.startswith("ollama") and self._is_small(r)
               and r.physical_name != name]
        return ResidencyPlan(gpu_main=name, cpu_pinned=cpu, unload=unload,
                             reason="single large model on GPU; small specialists on CPU")

    def pin_small_to_cpu(self) -> list[str]:
        """Registry runtime options: small Ollama models run on CPU (num_gpu 0) leaving VRAM free."""
        pinned = []
        for r in self.registry.all():
            if r.provider.startswith("ollama") and self._is_small(r) and r.tier <= 1:
                r.runtime_options["num_gpu"] = 0
                pinned.append(r.id)
        return pinned

    async def loaded(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(base_url=self.url, timeout=10) as c:
            return (await c.get("/api/ps")).json().get("models", [])

    async def ensure(self, wanted: str) -> ResidencyPlan:
        plan = self.plan(await self.loaded(), wanted)
        async with httpx.AsyncClient(base_url=self.url, timeout=60) as c:
            for n in plan.unload:
                await c.post("/api/generate", json={"model": n, "keep_alive": 0})
        return plan
