# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA AutoBuilder: build the best engine the physical machine can run (``hydra build --auto``).

    detect GPU -> measure VRAM/RAM/CPU -> candidate runtime configs (quant x context x KV x offload)
    -> benchmark each (stability, VRAM, TTFT, tok/s, OOM) -> fall back if needed -> best config
    -> signed runtime-manifest.json -> apply to .env / model catalogue -> start HYDRA

Two measurement backends: ``llama-server`` (spawned per candidate: KV-cache types, -ngl,
context) and Ollama (per-request ``num_ctx``/``num_gpu`` options; KV type is a server
setting, OLLAMA_KV_CACHE_TYPE, recorded but not varied)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from hydra.core.atomic import write_text_atomic
from hydra.core.hashing import canonical_json, now_iso, sha256_hex
from hydra.edge.profiles import HardwareProfile, detect_profile, llama_server_args
from hydra.model_factory.physical.gpu_telemetry import PeakVramMonitor

PROMPT = "Reply with exactly ten short English words about local AI inference."


class BuildCandidate(BaseModel):
    quant: str = "Q4_K_M"
    context: int = 8192
    gpu_layers: int = 99
    kv_k: str = "q8_0"
    kv_v: str = "q8_0"

    def score(self, b: dict[str, Any]) -> float:
        if not b.get("stable"):
            return -1e9
        tok_s = float(b.get("tokens_per_second", 0.0))
        ttft = float(b.get("ttft_ms", 99999.0))
        vram = b.get("vram_peak_mb")
        vram = 99999.0 if vram is None else float(vram)  # unknown VRAM scores as worst case
        ctx_bonus = min(self.context, 32768) / 8192 * 2.0
        offload_penalty = 0.0 if b.get("fully_on_gpu", True) else 15.0
        ratio = float(b.get("vram_ratio", 0.0))
        headroom_penalty = 100.0 * max(0.0, ratio - 0.80)  # keep >= 20% VRAM for KV growth + CUDA runtime
        return round(tok_s * 2.0 - ttft / 1000.0 - vram / 10000.0 + ctx_bonus - offload_penalty - headroom_penalty, 3)


def candidates_for(profile: HardwareProfile) -> list[BuildCandidate]:
    if profile.profile == "rtx3060ti":
        return [BuildCandidate(quant="Q5_K_M", context=4096), BuildCandidate(quant="Q4_K_M", context=4096),
                BuildCandidate(quant="Q4_K_M", context=8192), BuildCandidate(quant="Q4_K_M", context=8192, kv_k="q4_0",
                                                                             kv_v="q4_0"),
                BuildCandidate(quant="Q3_K_M", context=8192), BuildCandidate(quant="Q4_K_M", context=16384)]
    base = profile.context
    return [BuildCandidate(quant=profile.quant, context=c, gpu_layers=profile.gpu_layers, kv_k=profile.kv_k,
                           kv_v=profile.kv_v) for c in sorted({max(2048, base // 2), base, base * 2})]


async def bench_ollama(model: str, c: BuildCandidate, base_url: str = "http://localhost:11434",
                       timeout: float = 600) -> dict[str, Any]:
    opts = {"num_ctx": c.context, "num_gpu": c.gpu_layers, "temperature": 0, "num_predict": 64}
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as cl:
        try:
            await cl.post("/api/generate", json={"model": model, "keep_alive": 0})  # unload: measure a cold config
            t0 = time.perf_counter()
            r = await cl.post("/api/generate", json={"model": model, "prompt": PROMPT, "stream": False,
                                                     "options": opts, "keep_alive": "5m"})
            r.raise_for_status()
            d = r.json()
            wall = (time.perf_counter() - t0) * 1000
            ps = (await cl.get("/api/ps")).json().get("models", [])
            m = next((x for x in ps if x.get("name", "").startswith(model.split(":")[0])), {})
            size, vram = m.get("size", 0), m.get("size_vram", 0)
            eval_s = d.get("eval_duration", 0) / 1e9
            return {"stable": True, "tokens_per_second": round(d.get("eval_count", 0) / eval_s, 2) if eval_s else 0,
                    "ttft_ms": round((d.get("load_duration", 0) + d.get("prompt_eval_duration", 0)) / 1e6, 1),
                    "load_ms": round(d.get("load_duration", 0) / 1e6, 1), "wall_ms": round(wall, 1),
                    "vram_peak_mb": round(vram / 2**20), "model_size_mb": round(size / 2**20),
                    "fully_on_gpu": bool(size) and vram >= size * 0.99, "candidate": c.model_dump(),
                    "sample": d.get("response", "")[:120]}
        except Exception as exc:
            return {"stable": False, "error": f"{type(exc).__name__}: {exc}"[:300], "candidate": c.model_dump()}


async def bench_llama_server(server: str, model_path: str, c: BuildCandidate, profile: HardwareProfile,
                             port: int = 18181) -> dict[str, Any]:
    args = [server, *llama_server_args(profile, model_path, port, c.context, c.kv_k, c.kv_v, c.gpu_layers)]
    log = tempfile.NamedTemporaryFile("w+", delete=False, suffix=".log")
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    try:
        async with httpx.AsyncClient(timeout=120) as cl:
            deadline = time.time() + 90
            while time.time() < deadline:
                if proc.poll() is not None:
                    return {"stable": False, "error": "server exited (OOM?)", "candidate": c.model_dump()}
                try:
                    if (await cl.get(f"http://127.0.0.1:{port}/health")).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
            else:
                return {"stable": False, "error": "server_start_timeout", "candidate": c.model_dump()}
            # sample VRAM while generating (peak, not before/after), failing closed without telemetry
            monitor = PeakVramMonitor(interval_seconds=0.1)
            sampling = asyncio.create_task(monitor.run())
            t0 = time.perf_counter()
            try:
                r = await cl.post(f"http://127.0.0.1:{port}/v1/chat/completions", json={
                    "model": "local", "messages": [{"role": "user", "content": PROMPT}], "temperature": 0,
                    "max_tokens": 64})
            finally:
                monitor.stop()
                await sampling
            r.raise_for_status()
            d = r.json()
            elapsed = time.perf_counter() - t0
            timings = d.get("timings", {})
            result = {"stable": True, "tokens_per_second": round(timings.get("predicted_per_second", 0) or
                                                                 d["usage"]["completion_tokens"] / max(elapsed, 1e-3), 2),
                      "ttft_ms": round(timings.get("prompt_ms", elapsed * 1000), 1),
                      "vram_peak_mb": monitor.peak_mb if monitor.samples else None,
                      "vram_samples": monitor.samples, "fully_on_gpu": c.gpu_layers >= 99,
                      "candidate": c.model_dump(), "sample": d["choices"][0]["message"]["content"][:120]}
            if monitor.error or not monitor.samples:
                result["telemetry_error"] = monitor.error or "no GPU telemetry samples"
            return result
    except Exception as exc:
        return {"stable": False, "error": f"{type(exc).__name__}: {exc}"[:300], "candidate": c.model_dump()}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def eligible(result: dict[str, Any], profile: HardwareProfile) -> bool:
    """A GPU configuration without VRAM evidence cannot be selected (fail closed)."""
    if profile.vram_mb <= 0:
        return True
    return "telemetry_error" not in result and result.get("vram_peak_mb") is not None


class RuntimeManifest(BaseModel):
    created_at: str = Field(default_factory=now_iso)
    runtime: str
    model: str
    hardware: dict[str, Any]
    selected: dict[str, Any] | None
    all_results: list[dict[str, Any]]
    signature: dict[str, Any] | None = None


async def autobuild(*, model: str, runtime: str = "ollama", ollama_url: str = "http://localhost:11434",
                    llama_server: str | None = None, profile: HardwareProfile | None = None,
                    candidates: list[BuildCandidate] | None = None, signer=None) -> RuntimeManifest:
    profile = profile or detect_profile()
    cands = candidates or candidates_for(profile)
    if runtime == "ollama":  # quant is fixed by the pulled tag: vary context / offload only
        seen, uniq = set(), []
        for c in cands:
            key = (c.context, c.gpu_layers)
            if key not in seen:
                seen.add(key)
                uniq.append(c)
        cands = uniq
    results = []
    for i, c in enumerate(cands):
        if runtime == "ollama":
            r = await bench_ollama(model, c, ollama_url)
        else:
            server = llama_server or shutil.which("llama-server")
            if not server:
                raise FileNotFoundError("llama-server not found (build llama.cpp or set HYDRA_LLAMA_SERVER)")
            r = await bench_llama_server(server, model, c, profile, port=18181 + i)
        if r.get("vram_peak_mb") and profile.vram_mb:
            r["vram_ratio"] = round(r["vram_peak_mb"] / profile.vram_mb, 3)
        r["score"] = c.score(r)
        results.append(r)
    stable = [r for r in results if r.get("stable") and eligible(r, profile)]
    best = max(stable, key=lambda r: r["score"]) if stable else None
    m = RuntimeManifest(runtime=runtime, model=model, hardware=profile.as_dict(), selected=best, all_results=results)
    if signer is not None:
        m.signature = signer.envelope(sha256_hex(canonical_json(m.model_dump(exclude={"signature"}))))
    return m


def apply_manifest(manifest: RuntimeManifest, *, env_path: Path | None = None, registry=None,
                   model_id: str | None = None) -> dict[str, Any]:
    """Apply the winning configuration to .env and/or the in-memory registry (runtime_options)."""
    if manifest.selected is None:
        raise ValueError("no stable candidate in manifest")
    c = manifest.selected["candidate"]
    applied = {"HYDRA_CONTEXT": str(c["context"]), "HYDRA_GPU_LAYERS": str(c["gpu_layers"]), "HYDRA_PARALLEL": "1",
               "HYDRA_KV_K": c["kv_k"], "HYDRA_KV_V": c["kv_v"]}
    if env_path is not None:
        existing: dict[str, str] = {}
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v
        existing.update(applied)
        write_text_atomic(env_path, "\n".join(f"{k}={v}" for k, v in existing.items()) + "\n")
    if registry is not None:
        for m in registry.all():
            if (model_id and m.id == model_id) or m.physical_name == manifest.model:
                m.runtime_options.update({"num_ctx": c["context"], "num_gpu": c["gpu_layers"]})
                applied["model"] = m.id
    return applied


def save_manifest(m: RuntimeManifest, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, m.model_dump_json(indent=2))
    return path
