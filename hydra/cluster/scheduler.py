# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Global Cognitive Scheduler: hardware-, residency-, cache- and SLA-aware placement.

It answers simultaneously: which model, which variant, which node, which GPU, which
runtime, which precision, which adapter, which cache exists, which queue, which SLA and
how much budget is left.

    Score = w_q·Q + w_c·CacheHit + w_r·Residency + w_p·Privacy
            - w_l·Latency - w_m·Migration - w_o·Queue - w_$·Cost - w_e·Energy

A slightly worse variant that is already loaded and holds the prompt prefix in its KV
cache can win because it saves seconds."""

from __future__ import annotations

import hashlib
import math
import threading
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from hydra.cluster.nodes import HardwareNode, NodeRegistry


class SchedulingMode(str, Enum):
    FAST = "fast"
    CHEAP = "cheap"
    PRIVATE = "private"
    ECO = "eco"
    MAX_QUALITY = "max_quality"
    DEEP = "deep"
    BALANCED = "balanced"


WEIGHTS: dict[str, dict[str, float]] = {
    "balanced": {"quality": 0.35, "residency": 0.15, "cache": 0.10, "privacy": 0.10, "queue": 0.10,
                 "latency": 0.10, "load": 0.05, "cost": 0.05, "energy": 0.0},
    "fast": {"quality": 0.25, "residency": 0.2, "cache": 0.15, "privacy": 0.05, "queue": 0.15, "latency": 0.5,
             "load": 0.1, "cost": 0.02, "energy": 0.0},
    "cheap": {"quality": 0.3, "residency": 0.1, "cache": 0.1, "privacy": 0.05, "queue": 0.05, "latency": 0.05,
              "load": 0.05, "cost": 0.5, "energy": 0.05},
    "eco": {"quality": 0.3, "residency": 0.15, "cache": 0.1, "privacy": 0.05, "queue": 0.05, "latency": 0.05,
            "load": 0.1, "cost": 0.1, "energy": 0.4},
    "max_quality": {"quality": 0.8, "residency": 0.02, "cache": 0.02, "privacy": 0.05, "queue": 0.02,
                    "latency": 0.01, "load": 0.01, "cost": 0.01, "energy": 0.0},
    "deep": {"quality": 0.7, "residency": 0.05, "cache": 0.05, "privacy": 0.05, "queue": 0.05, "latency": 0.02,
             "load": 0.02, "cost": 0.02, "energy": 0.0},
    "private": {"quality": 0.35, "residency": 0.15, "cache": 0.1, "privacy": 1.0, "queue": 0.1, "latency": 0.1,
                "load": 0.05, "cost": 0.02, "energy": 0.0},
}


class WorkEstimate(BaseModel):
    prompt_tokens: int
    expected_output_tokens: int
    expected_prefill_ms: float
    expected_decode_ms: float
    expected_kv_gb: float

    @property
    def total_ms(self) -> float:
        return self.expected_prefill_ms + self.expected_decode_ms


def estimate_work(prompt_chars: int, expected_output_tokens: int, *, prefill_tok_s: float = 2000,
                  decode_tok_s: float = 40, kv_mb_per_1k_tokens: float = 64) -> WorkEstimate:
    pt = max(1, prompt_chars // 4)
    return WorkEstimate(prompt_tokens=pt, expected_output_tokens=expected_output_tokens,
                        expected_prefill_ms=round(pt / prefill_tok_s * 1000, 1),
                        expected_decode_ms=round(expected_output_tokens / decode_tok_s * 1000, 1),
                        expected_kv_gb=round((pt + expected_output_tokens) / 1000 * kv_mb_per_1k_tokens / 1024, 3))


class SLA(BaseModel):
    target_ttft_ms: int = 2000
    max_total_ms: int = 60_000
    quality_min: float = 0.0


SLA_CLASSES = {"realtime": SLA(target_ttft_ms=300, max_total_ms=3000),
               "interactive": SLA(target_ttft_ms=900, max_total_ms=12_000, quality_min=0.6),
               "normal": SLA(target_ttft_ms=3000, max_total_ms=60_000),
               "batch": SLA(target_ttft_ms=60_000, max_total_ms=3_600_000),
               "background_lab": SLA(target_ttft_ms=600_000, max_total_ms=86_400_000)}


class PrefixIndex:
    """KV locality: which node recently served a given prompt prefix (system prompt, memory pack,
    document pack, tool schema) -> route there to reuse the prefix cache."""

    def __init__(self, max_entries: int = 50_000, ttl_s: float = 1800) -> None:
        self.entries: dict[str, dict[str, float]] = {}
        self.affinity: dict[str, tuple[str, float]] = {}
        self.max_entries = max_entries
        self.ttl = ttl_s

    @staticmethod
    def fingerprints(system: str = "", memory: str = "", documents: str = "", tools: str = "") -> list[str]:
        acc, out = "", []
        for part in (system, memory, documents, tools):
            acc += part
            if part:
                out.append(hashlib.sha256(acc.encode()).hexdigest()[:24])
        return out

    def record(self, prefixes: list[str], node_id: str, conversation: str | None = None) -> None:
        now = time.time()
        for p in prefixes:
            self.entries.setdefault(p, {})[node_id] = now
        if conversation:
            self.affinity[conversation] = (node_id, now)
        if len(self.entries) > self.max_entries:
            for k in sorted(self.entries, key=lambda k: max(self.entries[k].values()))[: self.max_entries // 10]:
                self.entries.pop(k, None)

    def locality(self, prefixes: list[str], node_id: str) -> float:
        now = time.time()
        if not prefixes:
            return 0.0
        hits = sum(1 for p in prefixes if now - self.entries.get(p, {}).get(node_id, 0) < self.ttl)
        return hits / len(prefixes)

    def affinity_node(self, conversation: str | None) -> str | None:
        if not conversation or conversation not in self.affinity:
            return None
        node, at = self.affinity[conversation]
        return node if time.time() - at < self.ttl else None


class ParallelPlan(BaseModel):
    tensor_parallel: int = 1
    pipeline_parallel: int = 1
    data_parallel: int = 1
    expert_parallel: bool = False

    def vllm_args(self) -> list[str]:
        args = ["--tensor-parallel-size", str(self.tensor_parallel)]
        if self.pipeline_parallel > 1:
            args += ["--pipeline-parallel-size", str(self.pipeline_parallel)]
        if self.data_parallel > 1:
            args += ["--data-parallel-size", str(self.data_parallel)]
        if self.expert_parallel:
            args.append("--enable-expert-parallel")
        return args


def create_parallel_plan(model_memory_gb: float, is_moe: bool, gpus: int, single_gpu_vram_gb: float,
                         nodes: int = 1) -> ParallelPlan:
    if gpus <= 1:
        return ParallelPlan()
    if is_moe:
        return ParallelPlan(tensor_parallel=1, data_parallel=gpus, expert_parallel=True)
    usable = single_gpu_vram_gb * 0.9
    if model_memory_gb > usable:
        tp = 1
        while tp < gpus and model_memory_gb / tp > usable:
            tp *= 2
        tp = min(tp, gpus)
        pp = nodes if nodes > 1 and model_memory_gb / tp > usable else 1
        return ParallelPlan(tensor_parallel=tp, pipeline_parallel=pp, data_parallel=max(1, gpus // (tp * pp)))
    return ParallelPlan(data_parallel=gpus)


class Reservation(BaseModel):
    id: str
    node_id: str
    gpu_id: str | None
    memory_gb: float
    expires_at: float


class AdmissionController:
    """estimate memory + KV growth -> check concurrency -> reserve capacity -> run (fewer OOMs)."""

    def __init__(self, headroom_gb: float = 0.5) -> None:
        self.reservations: dict[str, Reservation] = {}
        self.headroom = headroom_gb
        self._lock = threading.Lock()

    def reserved(self, node_id: str, gpu_id: str | None = None) -> float:
        now = time.time()
        return sum(r.memory_gb for r in self.reservations.values() if r.node_id == node_id
                   and (gpu_id is None or r.gpu_id == gpu_id) and r.expires_at > now)

    def reserve(self, node: HardwareNode, memory_gb: float, ttl_s: float = 300, resident: bool = False
                ) -> Reservation | None:
        """``resident``: the weights are already loaded -> only KV growth must fit."""
        with self._lock:
            cands = node.gpus or []
            for g in sorted(cands, key=lambda g: -g.free_vram_gb):
                free = g.free_vram_gb - self.reserved(node.id, g.id) - self.headroom
                if free >= memory_gb:
                    r = Reservation(id=hashlib.sha1(f"{node.id}{time.time()}{memory_gb}".encode()).hexdigest()[:12],
                                    node_id=node.id, gpu_id=g.id, memory_gb=memory_gb, expires_at=time.time() + ttl_s)
                    self.reservations[r.id] = r
                    return r
            if not cands and node.free_ram_gb - self.reserved(node.id) - self.headroom >= memory_gb:
                r = Reservation(id=hashlib.sha1(f"{node.id}{time.time()}".encode()).hexdigest()[:12],
                                node_id=node.id, gpu_id=None, memory_gb=memory_gb, expires_at=time.time() + ttl_s)
                self.reservations[r.id] = r
                return r
        return None

    def release(self, reservation_id: str) -> None:
        self.reservations.pop(reservation_id, None)


class DraftRelationship(BaseModel):
    target_model: str
    draft_model: str
    acceptance_rate: float
    speedup: float


class Placement(BaseModel):
    model_id: str
    node_id: str
    score: float
    components: dict[str, float] = Field(default_factory=dict)
    predicted_ms: float = 0.0
    resident: bool = False
    draft_model: str | None = None
    degradation_level: int = 0
    reservation: str | None = None


DEGRADATION_LEVELS = ["full ensemble", "single large model", "medium specialist", "local small",
                      "cached / limited response"]


class GlobalScheduler:
    def __init__(self, nodes: NodeRegistry, admission: AdmissionController | None = None,
                 prefixes: PrefixIndex | None = None) -> None:
        self.nodes = nodes
        self.admission = admission or AdmissionController()
        self.prefixes = prefixes or PrefixIndex()
        self.drafts: dict[str, DraftRelationship] = {}

    def register_draft(self, rel: DraftRelationship) -> None:
        if rel.acceptance_rate >= 0.5 and rel.speedup > 1.1:
            self.drafts[rel.target_model] = rel

    def execution_score(self, model, node: HardwareNode, *, quality: float, mode: str = "balanced",
                        private: bool = False, prefixes: list[str] | None = None, work: WorkEstimate | None = None,
                        sla: SLA | None = None) -> tuple[float, dict[str, float], float]:
        w = WEIGHTS.get(mode, WEIGHTS["balanced"])
        resident = any(r.model_id in (model.id, model.physical_name) and r.tier == "HOT" for r in node.residency)
        residency = 1.0 if resident else 0.3 if any(r.model_id in (model.id, model.physical_name)
                                                   for r in node.residency) else 0.0
        cache = self.prefixes.locality(prefixes or [], node.id)
        privacy = 1.0 if (model.local and node.labels.get("zone", "local") != "public") else (0.0 if private else 0.5)
        queue = min(1.0, (node.queue_depth + model.queue_depth) / 8)
        load_ms = 0 if resident else 1500 + 400 * (getattr(model, "tier", 2))
        pred_ms = (work.total_ms if work else model.predicted_latency_ms) * (1 + queue) + load_ms
        latency = min(1.0, pred_ms / max(1.0, (sla.max_total_ms if sla else 60_000)))
        gpu_power = sum(g.power_w or 150 for g in node.gpus) or 65
        energy_j = gpu_power * pred_ms / 1000
        energy = min(1.0, energy_j / 20_000)
        cost = min(1.0, (model.output_cost + model.input_cost) / 30)
        comps = {"quality": quality, "residency": residency, "cache": cache, "privacy": privacy, "queue": queue,
                 "latency": latency, "load": 0.0 if resident else 1.0, "cost": cost, "energy": energy}
        score = (w["quality"] * quality + w["residency"] * residency + w["cache"] * cache + w["privacy"] * privacy
                 - w["queue"] * queue - w["latency"] * latency - w["load"] * comps["load"] - w["cost"] * cost
                 - w["energy"] * energy)
        return round(score, 4), {k: round(v, 3) for k, v in comps.items()}, round(pred_ms, 1)

    def place(self, models: list, *, quality_of, mode: str = "balanced", private: bool = False,
              prefixes: list[str] | None = None, conversation: str | None = None, work: WorkEstimate | None = None,
              sla: SLA | None = None, memory_of=None, reserve: bool = False) -> list[Placement]:
        nodes = self.nodes.healthy()
        affinity = self.prefixes.affinity_node(conversation)
        out: list[Placement] = []
        for m in models:
            for n in nodes or [HardwareNode(id="local")]:
                if private and not m.local:
                    continue
                s, comps, pred = self.execution_score(m, n, quality=quality_of(m), mode=mode, private=private,
                                                      prefixes=prefixes, work=work, sla=sla)
                if affinity == n.id:
                    s += 0.05
                if sla and pred > sla.max_total_ms:
                    continue  # deadline-aware: never pick what cannot meet the SLA
                p = Placement(model_id=m.id, node_id=n.id, score=s, components=comps, predicted_ms=pred,
                              resident=comps["residency"] == 1.0,
                              draft_model=self.drafts.get(m.id).draft_model if m.id in self.drafts else None)
                out.append(p)
        out.sort(key=lambda p: -p.score)
        if reserve and out and memory_of is not None:
            for p in out:
                node = self.nodes.nodes.get(p.node_id)
                if node is None:
                    break
                need = memory_of(p.model_id) if not p.resident else (work.expected_kv_gb if work else 0.5)
                r = self.admission.reserve(node, need, resident=p.resident)
                if r is not None:
                    p.reservation = r.id
                    break
        return out

    def rerank(self, ranked: list, *, quality_of, mode: str, private: bool, prefixes: list[str] | None = None,
               conversation: str | None = None) -> list:
        """Kernel hook: reorder the router's ranking by cluster placement (keeps every model)."""
        if not self.nodes.healthy():
            return ranked
        best: dict[str, float] = {}
        for p in self.place(ranked, quality_of=quality_of, mode=mode, private=private, prefixes=prefixes,
                            conversation=conversation):
            best[p.model_id] = max(best.get(p.model_id, -math.inf), p.score)
        return sorted(ranked, key=lambda m: -best.get(m.id, -math.inf))

    @staticmethod
    def quant_fallback(variants: list[dict[str, Any]], free_gb: float) -> dict[str, Any] | None:
        """BF16 -> FP8 -> AWQ -> GGUF Q5 -> GGUF Q4: the best variant that still fits."""
        fits = [v for v in variants if v.get("memory_gb", 1e9) <= free_gb]
        return max(fits, key=lambda v: (v.get("quality", 0), -v.get("memory_gb", 0)), default=None)

    @staticmethod
    def degradation_level(queue_pressure: float, gpu_available: bool) -> int:
        if not gpu_available:
            return 3
        if queue_pressure > 0.95:
            return 4
        if queue_pressure > 0.8:
            return 2
        if queue_pressure > 0.6:
            return 1
        return 0

    def recover_oom(self, model_id: str, node_id: str, variants: list[dict[str, Any]]) -> dict[str, Any]:
        """MODEL_FAILED reason=OOM -> reduce batch | move node | smaller quant | fallback model."""
        node = self.nodes.nodes.get(node_id)
        others = [n for n in self.nodes.healthy() if n.id != node_id]
        smaller = self.quant_fallback([v for v in variants if v.get("model_id", model_id) == model_id],
                                      (node.free_vram_gb if node else 0) * 0.9)
        if smaller:
            return {"action": "smaller_quant", "variant": smaller}
        target = max(others, key=lambda n: n.free_vram_gb, default=None)
        if target is not None:
            return {"action": "move_node", "node": target.id}
        return {"action": "reduce_batch_and_fallback", "degradation_level": 2}
