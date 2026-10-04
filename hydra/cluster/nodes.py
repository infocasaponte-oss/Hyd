# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Hardware Registry, Model Residency Registry and the HOT/WARM/COLD warm pool.

Every worker node sends heartbeats (``POST /v1/cluster/heartbeat``): GPUs, free VRAM,
utilisation, queue depth, KV usage and which model variants are loaded. The global
scheduler sees the whole cluster from this registry."""

from __future__ import annotations

import os
import platform
import socket
import subprocess
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from hydra.core.hashing import now_iso


class GPUDevice(BaseModel):
    id: str
    vendor: str = "nvidia"
    model: str = ""
    total_vram_gb: float = 0.0
    free_vram_gb: float = 0.0
    utilization: float = 0.0
    temperature: float | None = None
    power_w: float | None = None
    compute_capability: str | None = None


class ModelResidency(BaseModel):
    model_id: str
    variant_id: str | None = None
    node_id: str
    devices: list[str] = Field(default_factory=list)
    loaded: bool = True
    memory_gb: float = 0.0
    active_requests: int = 0
    kv_cache_usage: float = 0.0
    tier: str = "HOT"  # HOT (in GPU) | WARM (RAM / local NVMe) | COLD (artifact store)
    last_used: float = Field(default_factory=time.time)


class HardwareNode(BaseModel):
    id: str
    hostname: str = ""
    cpu_arch: str = ""
    cpu_cores: int = 0
    system_ram_gb: float = 0.0
    free_ram_gb: float = 0.0
    gpus: list[GPUDevice] = Field(default_factory=list)
    network_class: str = "lan"
    runtimes: list[str] = Field(default_factory=list)
    endpoints: dict[str, str] = Field(default_factory=dict)
    queue_depth: int = 0
    residency: list[ModelResidency] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    """e.g. {"role": "gpu|edge|lab", "residency": "eu-west", "tenant": "..."}"""
    healthy: bool = True
    last_heartbeat: float = Field(default_factory=time.time)
    energy_price_eur_kwh: float = 0.20

    @property
    def gpu_count(self) -> int:
        return len(self.gpus)

    @property
    def free_vram_gb(self) -> float:
        return sum(g.free_vram_gb for g in self.gpus)

    @property
    def max_single_gpu_vram(self) -> float:
        return max((g.total_vram_gb for g in self.gpus), default=0.0)


def _nvidia() -> list[GPUDevice]:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free,utilization.gpu,"
                              "temperature.gpu,power.draw,compute_cap", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue

        def f(i: int) -> float | None:
            try:
                return float(parts[i])
            except (ValueError, IndexError):
                return None
        gpus.append(GPUDevice(id=f"GPU{parts[0]}", model=parts[1], total_vram_gb=round((f(2) or 0) / 1024, 2),
                              free_vram_gb=round((f(3) or 0) / 1024, 2), utilization=(f(4) or 0) / 100,
                              temperature=f(5), power_w=f(6), compute_capability=parts[7] if len(parts) > 7 else None))
    return gpus


def _ram() -> tuple[float, float]:
    try:
        from hydra.model_factory.hardware import _ram_gb

        total = _ram_gb()
    except Exception:
        total = 0.0
    free = 0.0
    try:
        if os.name == "nt":
            import ctypes

            class MEM(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong),
                            ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
            m = MEM()
            m.dwLength = ctypes.sizeof(MEM)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            free = m.ullAvailPhys / 2**30
        else:
            with open("/proc/meminfo") as fh:
                info = {x.split(":")[0]: x.split(":")[1] for x in fh}
            free = int(info["MemAvailable"].split()[0]) / 2**20
    except Exception:
        pass
    return round(total, 1), round(free, 1)


def detect_local_node(node_id: str | None = None, ollama_url: str | None = None) -> HardwareNode:
    total, free = _ram()
    runtimes, residency = [], []
    nid = node_id or socket.gethostname()
    if ollama_url:
        try:
            ps = httpx.get(f"{ollama_url}/api/ps", timeout=2).json()
            runtimes.append("ollama")
            for m in ps.get("models", []):
                vram = m.get("size_vram", 0) / 2**30
                residency.append(ModelResidency(model_id=m.get("name", "?"), node_id=nid, memory_gb=round(vram, 2),
                                                tier="HOT" if vram > 0 else "WARM"))
        except Exception:
            pass
    return HardwareNode(id=nid, hostname=socket.gethostname(), cpu_arch=platform.machine(),
                        cpu_cores=os.cpu_count() or 0, system_ram_gb=total, free_ram_gb=free, gpus=_nvidia(),
                        runtimes=runtimes, residency=residency,
                        endpoints={"ollama": ollama_url} if ollama_url else {})


class NodeRegistry:
    def __init__(self, heartbeat_ttl_s: float = 30.0) -> None:
        self.nodes: dict[str, HardwareNode] = {}
        self.ttl = heartbeat_ttl_s

    def heartbeat(self, node: HardwareNode) -> HardwareNode:
        node.last_heartbeat = time.time()
        node.healthy = True
        self.nodes[node.id] = node
        return node

    def sweep(self) -> list[str]:
        now = time.time()
        dead = [n.id for n in self.nodes.values() if now - n.last_heartbeat > self.ttl]
        for d in dead:
            self.nodes[d].healthy = False
        return dead

    def healthy(self) -> list[HardwareNode]:
        self.sweep()
        return [n for n in self.nodes.values() if n.healthy]

    def residency(self, model_id: str) -> list[ModelResidency]:
        return [r for n in self.healthy() for r in n.residency if r.model_id == model_id]

    def summary(self) -> dict[str, Any]:
        return {"nodes": len(self.nodes), "healthy": len(self.healthy()),
                "gpus": sum(n.gpu_count for n in self.nodes.values()),
                "free_vram_gb": round(sum(n.free_vram_gb for n in self.healthy()), 2),
                "loaded_models": sorted({r.model_id for n in self.healthy() for r in n.residency if r.tier == "HOT"}),
                "at": now_iso()}


class WarmPool:
    """HOT (GPU) / WARM (RAM, NVMe) / COLD (store). Frequently used -> HOT; unused 60 min -> WARM."""

    def __init__(self, idle_to_warm_s: float = 3600, promote_after: int = 3, window_s: float = 900) -> None:
        self.idle_to_warm_s = idle_to_warm_s
        self.promote_after = promote_after
        self.window_s = window_s
        self.uses: dict[str, list[float]] = {}
        self.tier: dict[str, str] = {}

    def touch(self, model_id: str) -> None:
        now = time.time()
        self.uses.setdefault(model_id, []).append(now)
        self.uses[model_id] = [t for t in self.uses[model_id] if now - t <= self.window_s]
        if len(self.uses[model_id]) >= self.promote_after:
            self.tier[model_id] = "HOT"
        else:
            self.tier.setdefault(model_id, "WARM")

    def plan(self) -> dict[str, list[str]]:
        now = time.time()
        demote = [m for m, t in self.tier.items() if t == "HOT" and (not self.uses.get(m)
                                                                      or now - self.uses[m][-1] > self.idle_to_warm_s)]
        for m in demote:
            self.tier[m] = "WARM"
        return {"hot": sorted(m for m, t in self.tier.items() if t == "HOT"),
                "warm": sorted(m for m, t in self.tier.items() if t == "WARM"), "demote": demote}
