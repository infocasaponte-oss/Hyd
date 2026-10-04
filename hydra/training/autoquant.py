# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""AutoQuant, tensor-aware AutoQuant, the Hardware Lab matrix and the Model Capability Graph.

    model -> calibration -> candidate quantizations -> benchmark -> quality delta -> Pareto search

Tensor-aware: instead of "everything Q4", learn per-tensor-group sensitivity
(embeddings Q8, attention Q/K Q6, attention V Q5, FFN Q4, output Q8) and search the
combination that minimises memory subject to Quality >= target (llama-quantize supports
per-tensor type overrides)."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from hydra.model_factory.hardware import BITS_PER_WEIGHT
from hydra.model_factory.quantizer import TensorOverride

AUTOQUANT_CANDIDATES = ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "IQ4_XS"]
LADDER = ["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "IQ4_XS", "Q3_K_M"]

# Typical share of parameters and relative sensitivity (quality loss per bit removed) of tensor groups
# in dense decoder-only transformers. Measured values (per-group KLD) replace these priors.
DEFAULT_GROUPS = {
    "token_embd": {"pattern": "token_embd", "share": 0.06, "sensitivity": 3.0},
    "output": {"pattern": "output", "share": 0.06, "sensitivity": 4.0},
    "attn_qk": {"pattern": "attn_(q|k)", "share": 0.10, "sensitivity": 1.5},
    "attn_v": {"pattern": "attn_v", "share": 0.05, "sensitivity": 2.0},
    "attn_output": {"pattern": "attn_output", "share": 0.08, "sensitivity": 1.0},
    "ffn": {"pattern": "ffn_(up|gate|down)", "share": 0.65, "sensitivity": 0.8},
}


class QuantCandidateResult(BaseModel):
    quant: str
    variant_id: str | None = None
    memory_gb: float
    quality: float
    tokens_per_second: float | None = None
    overrides: list[TensorOverride] = Field(default_factory=list)


def pareto_select(results: list[QuantCandidateResult], minimum_quality: float) -> dict[str, Any]:
    ok = [r for r in results if r.quality >= minimum_quality]
    frontier = [r for r in results if not any(
        (o.quality >= r.quality and o.memory_gb <= r.memory_gb and (o.tokens_per_second or 0) >= (r.tokens_per_second or 0))
        and (o.quality, -o.memory_gb) != (r.quality, -r.memory_gb) for o in results)]
    winner = min(ok, key=lambda r: (r.memory_gb, -r.quality)) if ok else None
    return {"winner": winner.model_dump() if winner else None, "frontier": [r.model_dump() for r in frontier],
            "rejected": [r.quant for r in results if r.quality < minimum_quality]}


class AutoQuant:
    """Build each candidate quant, evaluate it on the target hardware, select on the Pareto frontier."""

    def __init__(self, build: Callable[[str, str], Awaitable[Any]], evaluate: Callable[[Any], Awaitable[dict]],
                 candidates: list[str] | None = None) -> None:
        self.build = build
        self.evaluate = evaluate
        self.candidates = candidates or AUTOQUANT_CANDIDATES

    async def optimize(self, model: str, minimum_quality: float) -> dict[str, Any]:
        results = []
        for q in self.candidates:
            artifact = await self.build(model, q)
            if artifact is None:
                continue
            m = await self.evaluate(artifact)
            results.append(QuantCandidateResult(quant=q, variant_id=m.get("variant_id"), memory_gb=m["memory_gb"],
                                                quality=m["quality"], tokens_per_second=m.get("tokens_per_second")))
        return pareto_select(results, minimum_quality)


def _bits(q: str) -> float:
    return BITS_PER_WEIGHT.get(q, 4.8)


class TensorPlan(BaseModel):
    assignments: dict[str, str]
    overrides: list[TensorOverride]
    base_quant: str
    predicted_quality: float
    memory_gb: float
    bits_per_weight: float


def tensor_aware_plan(parameters: int, quality_target: float = 0.97, groups: dict[str, dict] | None = None,
                      base_quality: dict[str, float] | None = None) -> TensorPlan:
    """Greedy: start with every group at Q8_0, repeatedly lower the group with the smallest quality
    loss per GB saved while predicted quality stays >= target (min Memory s.t. Quality >= q)."""
    groups = groups or DEFAULT_GROUPS
    # quality retained per group per quant (1.0 at Q8_0), scaled by sensitivity
    base_quality = base_quality or {"Q8_0": 1.0, "Q6_K": 0.995, "Q5_K_M": 0.988, "Q4_K_M": 0.975, "IQ4_XS": 0.968,
                                    "Q3_K_M": 0.93}
    assign = {g: "Q8_0" for g in groups}

    def quality(a: dict[str, str]) -> float:
        loss = sum(groups[g]["share"] * groups[g]["sensitivity"] * (1 - base_quality[a[g]]) for g in a)
        return 1 - loss

    def memory(a: dict[str, str]) -> float:
        return sum(parameters * groups[g]["share"] * _bits(a[g]) / 8 / 2**30 for g in a)

    while True:
        best = None
        for g, q in assign.items():
            i = LADDER.index(q)
            if i + 1 >= len(LADDER):
                continue
            trial = {**assign, g: LADDER[i + 1]}
            qv = quality(trial)
            if qv < quality_target:
                continue
            saved = memory(assign) - memory(trial)
            lost = quality(assign) - qv
            ratio = lost / saved if saved > 0 else float("inf")
            if best is None or ratio < best[0]:
                best = (ratio, trial)
        if best is None:
            break
        assign = best[1]
    base = max(set(assign.values()), key=lambda q: sum(groups[g]["share"] for g in assign if assign[g] == q))
    overrides = [TensorOverride(pattern=groups[g]["pattern"], type=q) for g, q in assign.items() if q != base]
    total_bits = sum(groups[g]["share"] * _bits(assign[g]) for g in assign)
    return TensorPlan(assignments=assign, overrides=overrides, base_quant=base, predicted_quality=round(quality(assign), 4),
                      memory_gb=round(memory(assign), 3), bits_per_weight=round(total_bits, 3))


def hardware_matrix(variants: list, benchmarks: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Model Variant x Hardware from real benchmark results (the resolver never guesses)."""
    rows: dict[str, dict[str, Any]] = {}
    hw_set: set[str] = set()
    for v in variants:
        b = (benchmarks or {}).get(v.id) or (v.benchmark.model_dump() if getattr(v, "benchmark", None) else None)
        if not b:
            continue
        hw = b.get("hardware") or "local"
        hw_set.add(hw)
        tps = b.get("tokens_per_second") or 0
        grade = "excelente" if tps >= 60 else "bueno" if tps >= 20 else "lento" if tps > 0 else "—"
        rows.setdefault(v.id, {})[hw] = {"tokens_per_second": tps, "ttft_ms": b.get("ttft_ms"),
                                         "memory_gb": b.get("memory_gb"), "grade": grade}
    return {"hardware": sorted(hw_set), "variants": rows}


class CapabilityNode(BaseModel):
    logical: str
    capabilities: dict[str, float] = Field(default_factory=dict)
    languages: list[str] = Field(default_factory=list)
    tool_calling: bool = False
    adapters: dict[str, str] = Field(default_factory=dict)
    """capability -> adapter id"""
    variants: list[dict[str, Any]] = Field(default_factory=list)
    """{"id", "format", "quant", "memory_gb", "runtime", "local"}"""


class ModelCapabilityGraph:
    """logical model --supports--> capability, --adapter--> capability, --variants--> fp8/gguf/mlx."""

    def __init__(self) -> None:
        self.nodes: dict[str, CapabilityNode] = {}

    def add(self, node: CapabilityNode) -> None:
        self.nodes[node.logical] = node

    @classmethod
    def from_runtime(cls, registry, factory=None, adapters=None) -> ModelCapabilityGraph:
        g = cls()
        for m in registry.all():
            logical = m.logical_model or m.id
            n = g.nodes.get(logical) or CapabilityNode(logical=logical)
            caps = m.capabilities.model_dump()
            for k, v in caps.items():
                n.capabilities[k] = max(n.capabilities.get(k, 0), v)
            n.tool_calling = n.tool_calling or caps.get("tools", 0) > 0.5
            n.languages = sorted(set(n.languages) | {"es", "en"})
            n.variants.append({"id": m.id, "format": "runtime", "runtime": m.provider.split(":")[0], "local": m.local,
                               "memory_gb": None, "enabled": m.enabled})
            g.nodes[logical] = n
        if factory is not None:
            for v in factory.store.variants.values():
                n = g.nodes.get(v.logical_model) or CapabilityNode(logical=v.logical_model)
                n.variants.append({"id": v.id, "format": v.format.value if hasattr(v.format, "value") else v.format,
                                   "quant": v.quantization, "memory_gb": v.memory_gb or None, "runtime": v.runtime,
                                   "local": True, "quality": v.quality_score, "status": v.status})
                g.nodes[v.logical_model] = n
        for a in (adapters or []):
            n = g.nodes.get(a.base_model) or next((x for x in g.nodes.values()
                                                   if any(v["id"] == a.base_model for v in x.variants)), None)
            if n is not None:
                cap = a.logical_model.removeprefix("hydra-").split("-")[0]
                n.adapters[cap] = a.adapter_name
        return g

    def query(self, capability: str, *, local: bool = False, max_memory_gb: float | None = None,
              language: str | None = None, tool_calling: bool = False, min_quality: float = 0.0) -> list[dict[str, Any]]:
        out = []
        for n in self.nodes.values():
            q = n.capabilities.get(capability, 0.0)
            via_adapter = capability in n.adapters
            if q < min_quality and not via_adapter:
                continue
            if language and n.languages and language not in n.languages:
                continue
            if tool_calling and not n.tool_calling:
                continue
            for v in n.variants:
                if local and not v.get("local", True):
                    continue
                if max_memory_gb is not None and v.get("memory_gb") is not None and v["memory_gb"] > max_memory_gb:
                    continue
                out.append({"logical": n.logical, "variant": v["id"], "runtime": v.get("runtime"),
                            "adapter": n.adapters.get(capability), "quality": max(q, 0.9 if via_adapter else 0),
                            "memory_gb": v.get("memory_gb")})
        return sorted(out, key=lambda x: (-x["quality"], x["memory_gb"] or 0))
