# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Hardware/runtime-aware scheduling.

    GPU0 94% busy, vLLM queue = 18  ->  ideal model would take 12 s
    medium model on GPU1: -2.3% quality, 1.8 s  ->  choose GPU1

Polls runtime metrics (vLLM / llama.cpp Prometheus endpoints, Ollama /api/ps,
local nvidia-smi) and feeds ``current_load`` / ``queue_depth`` / predicted latency
into the registry, so the scorer penalises saturated runtimes automatically.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from hydra.registry.registry import ModelRegistry, refresh_installed_models

log = logging.getLogger("hydra.monitor")

_METRIC = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([-+0-9.eE]+|NaN)$")


def parse_prometheus(text: str) -> dict[str, float]:
    """Sum samples per metric name (labels are aggregated)."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        m = _METRIC.match(line.strip())
        if m and m.group(3) != "NaN":
            out[m.group(1)] = out.get(m.group(1), 0.0) + float(m.group(3))
    return out


class RuntimeLoad(BaseModel):
    running: float = 0
    waiting: float = 0
    kv_cache_usage: float = 0

    @property
    def load(self) -> float:
        queue = min(1.0, self.waiting / 8)
        return round(min(1.0, 0.5 * queue + 0.3 * self.kv_cache_usage + 0.2 * min(1.0, self.running / 16)), 4)


def load_from_metrics(m: dict[str, float]) -> RuntimeLoad:
    def first(*names: str) -> float:
        for n in names:
            if n in m:
                return m[n]
        return 0.0

    return RuntimeLoad(
        running=first("vllm:num_requests_running", "llamacpp:requests_processing"),
        waiting=first("vllm:num_requests_waiting", "llamacpp:requests_deferred"),
        kv_cache_usage=first("vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc", "llamacpp:kv_cache_usage_ratio"),
    )


class GPUStatus(BaseModel):
    index: int
    name: str
    utilization: float
    memory_used_mb: float
    memory_total_mb: float


async def query_gpus() -> list[GPUStatus]:
    if shutil.which("nvidia-smi") is None:
        return []
    proc = await asyncio.create_subprocess_exec(
        "nvidia-smi", "--query-gpu=index,name,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    gpus = []
    for line in out.decode(errors="replace").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 5:
            with contextlib.suppress(ValueError):
                gpus.append(GPUStatus(index=int(parts[0]), name=parts[1], utilization=float(parts[2]) / 100,
                                      memory_used_mb=float(parts[3]), memory_total_mb=float(parts[4])))
    return gpus


class RuntimeMonitor:
    def __init__(self, registry: ModelRegistry, interval_s: float = 5.0,
                 ollama_url: str | None = None, providers: dict | None = None) -> None:
        self.registry = registry
        self.interval_s = interval_s
        self.ollama_url = ollama_url
        self.providers = providers or {}
        self.client = httpx.AsyncClient(timeout=3)
        self.gpus: list[GPUStatus] = []
        self.loads: dict[str, RuntimeLoad] = {}
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self.client.aclose()

    async def _loop(self) -> None:
        while True:
            try:
                await self.poll()
            except Exception:
                log.debug("runtime poll failed", exc_info=True)
            await asyncio.sleep(self.interval_s)

    async def poll(self) -> None:
        # Probe the exact provider instances used by the invoker before scoring.
        # This prevents a dead vLLM endpoint from winning selection and only then
        # failing over to the internal Ollama coder backend.
        if self.providers:
            results = await asyncio.gather(
                *(self._probe_provider(name, provider) for name, provider in self.providers.items()),
                return_exceptions=True,
            )
            for name, healthy in zip(self.providers, results):
                if isinstance(healthy, bool):
                    self.registry.set_provider_health(name, healthy)
            with contextlib.suppress(Exception):  # a model pulled or removed at runtime changes routing
                await refresh_installed_models(self.registry, self.providers)

        self.gpus = await query_gpus()
        local_gpu_util = max((g.utilization for g in self.gpus), default=0.0)
        loaded_in_ollama = await self._ollama_loaded()
        for m in self.registry.all():
            if not m.endpoint and not m.provider.startswith(("vllm", "llamacpp", "ollama")):
                continue
            load = await self._runtime_load(m.endpoint) if m.endpoint else None
            if load is not None:
                self.loads[m.id] = load
                m.current_load = load.load
                m.queue_depth = int(load.waiting)
            elif m.provider.startswith("ollama"):
                # Local runtime: GPU utilisation + cold-start penalty when the model is not resident.
                cold = loaded_in_ollama is not None and m.physical_name not in loaded_in_ollama
                m.current_load = round(min(1.0, local_gpu_util * 0.7 + (0.3 if cold else 0.0)), 4)

    async def _probe_provider(self, name: str, provider) -> bool:
        try:
            healthy = await provider.health()
            log.debug("provider health %s=%s", name, healthy)
            return healthy
        except Exception:
            log.debug("provider health probe failed: %s", name, exc_info=True)
            return False

    async def _runtime_load(self, endpoint: str) -> RuntimeLoad | None:
        u = urlparse(endpoint)
        url = f"{u.scheme}://{u.netloc}/metrics"
        try:
            r = await self.client.get(url)
            if r.status_code != 200:
                return None
            return load_from_metrics(parse_prometheus(r.text))
        except Exception:
            return None

    async def _ollama_loaded(self) -> set[str] | None:
        if not self.ollama_url:
            return None
        try:
            r = await self.client.get(self.ollama_url.rstrip("/") + "/api/ps")
            return {m["name"] for m in r.json().get("models", [])} | {m["model"] for m in r.json().get("models", [])}
        except Exception:
            return None

    def snapshot(self) -> dict:
        return {
            "gpus": [g.model_dump() for g in self.gpus],
            "models": {m.id: {"load": m.current_load, "queue": m.queue_depth,
                              "predicted_latency_ms": round(m.predicted_latency_ms, 1)}
                       for m in self.registry.all()},
        }
