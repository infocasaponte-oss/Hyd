# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Capacity planning, predictive model loading, the economic model, SLO tracking and tenancy.

    monday 09:00 -> 8,000 req/min -> 08:50 load coder replicas, warm prefixes, add workers
    TotalCost = GPU + API + Energy + LatencyOpportunity
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DemandForecast(BaseModel):
    hour: int
    weekday: int | None = None
    expected_tasks: float
    mix: dict[str, float] = Field(default_factory=dict)
    preload: list[str] = Field(default_factory=list)


class CapacityPlanner:
    """Learns hourly demand per task type from history and proposes what to pre-load."""

    def __init__(self) -> None:
        self.hist: dict[tuple[int, int], Counter] = defaultdict(Counter)
        self.days: set[str] = set()

    def observe(self, when: datetime, task_type: str) -> None:
        self.hist[(when.weekday(), when.hour)][task_type] += 1
        self.days.add(when.date().isoformat())

    def fit(self, tasks: list) -> int:
        n = 0
        for t in tasks:
            created = getattr(t, "created_at", None)
            route = getattr(t, "route", None) or {}
            if created is not None:
                self.observe(created, route.get("task_type", "chat"))
                n += 1
        return n

    def forecast(self, when: datetime, models_for: dict[str, str] | None = None, min_share: float = 0.2
                 ) -> DemandForecast:
        weeks = max(1, len(self.days) // 7) or 1
        c = self.hist.get((when.weekday(), when.hour), Counter())
        total = sum(c.values())
        mix = {k: round(v / total, 3) for k, v in c.items()} if total else {}
        preload = sorted({(models_for or {}).get(k, k) for k, share in mix.items() if share >= min_share})
        return DemandForecast(hour=when.hour, weekday=when.weekday(), expected_tasks=round(total / weeks, 2),
                              mix=mix, preload=preload)


class CostBreakdown(BaseModel):
    gpu_seconds: float = 0.0
    gpu_cost: float = 0.0
    api_cost: float = 0.0
    energy_kwh: float = 0.0
    energy_cost: float = 0.0
    opportunity_cost: float = 0.0
    total: float = 0.0


class EconomicModel:
    def __init__(self, gpu_eur_hour: float = 0.6, energy_eur_kwh: float = 0.2, latency_eur_per_s: float = 0.001) -> None:
        self.gpu_eur_hour = gpu_eur_hour
        self.energy_eur_kwh = energy_eur_kwh
        self.latency_eur_per_s = latency_eur_per_s

    def cost(self, *, gpu_seconds: float = 0.0, gpu_power_w: float = 200, api_input_tokens: int = 0,
             api_output_tokens: int = 0, api_in_per_m: float = 0.0, api_out_per_m: float = 0.0,
             latency_s: float = 0.0, gpu_busy: float = 0.0) -> CostBreakdown:
        """``gpu_busy`` in [0,1]: a saturated GPU has a higher opportunity cost than a cloud call."""
        kwh = gpu_power_w * gpu_seconds / 3_600_000
        b = CostBreakdown(gpu_seconds=gpu_seconds, gpu_cost=gpu_seconds / 3600 * self.gpu_eur_hour,
                          api_cost=(api_input_tokens * api_in_per_m + api_output_tokens * api_out_per_m) / 1e6,
                          energy_kwh=kwh, energy_cost=kwh * self.energy_eur_kwh,
                          opportunity_cost=latency_s * self.latency_eur_per_s * (1 + 3 * gpu_busy ** 2))
        b.total = round(b.gpu_cost + b.api_cost + b.energy_cost + b.opportunity_cost, 6)
        return b


class SLOTracker:
    def __init__(self) -> None:
        self.samples: dict[str, list[tuple[float, float, bool]]] = defaultdict(list)

    def record(self, cls: str, ttft_ms: float, total_ms: float, ok: bool) -> None:
        self.samples[cls].append((ttft_ms, total_ms, ok))
        self.samples[cls] = self.samples[cls][-10_000:]

    @staticmethod
    def pct(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        v = sorted(values)
        return round(v[min(len(v) - 1, max(0, math.ceil(p / 100 * len(v)) - 1))], 1)

    def report(self, contracts: dict[str, dict[str, float]] | None = None) -> dict[str, Any]:
        out = {}
        for cls, s in self.samples.items():
            ttft = [x[0] for x in s]
            tot = [x[1] for x in s]
            r = {"n": len(s), "p50_ttft_ms": self.pct(ttft, 50), "p95_ttft_ms": self.pct(ttft, 95),
                 "p99_total_ms": self.pct(tot, 99), "availability": round(sum(x[2] for x in s) / len(s), 4)}
            c = (contracts or {}).get(cls)
            if c:
                r["met"] = (r["p95_ttft_ms"] <= c.get("p95_ttft_ms", 1e12) and
                            r["p99_total_ms"] <= c.get("p99_total_ms", 1e12) and
                            r["availability"] >= c.get("availability", 0))
            out[cls] = r
        return out


class Tenant(BaseModel):
    id: str
    name: str = ""
    monthly_budget_eur: float | None = None
    spent_eur: float = 0.0
    allowed_models: list[str] = Field(default_factory=lambda: ["*"])
    local_only: bool = False
    data_residency: str | None = None
    memory_namespace: str = ""
    tools: list[str] = Field(default_factory=lambda: ["*"])


class TenantRegistry:
    """Multi-tenant isolation: memory, tools, credentials, budgets, model permissions, residency."""

    def __init__(self) -> None:
        self.tenants: dict[str, Tenant] = {}

    def add(self, t: Tenant) -> Tenant:
        t.memory_namespace = t.memory_namespace or f"tenant:{t.id}"
        self.tenants[t.id] = t
        return t

    def check(self, tenant_id: str | None, *, model: str | None = None, local: bool = True, cost: float = 0.0,
              tool: str | None = None) -> tuple[bool, str]:
        if tenant_id is None:
            return True, "no tenant"
        t = self.tenants.get(tenant_id)
        if t is None:
            return False, f"unknown tenant {tenant_id}"
        if model and "*" not in t.allowed_models and model not in t.allowed_models:
            return False, f"model {model} not allowed for tenant"
        if t.local_only and not local:
            return False, "tenant requires local models"
        if tool and "*" not in t.tools and tool not in t.tools:
            return False, f"tool {tool} not allowed for tenant"
        if t.monthly_budget_eur is not None and t.spent_eur + cost > t.monthly_budget_eur:
            return False, "tenant budget exhausted"
        return True, "ok"

    def charge(self, tenant_id: str | None, cost: float) -> None:
        if tenant_id in self.tenants:
            self.tenants[tenant_id].spent_eur += cost
