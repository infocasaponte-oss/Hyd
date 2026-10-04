# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Full observability: OpenTelemetry GenAI spans, cognitive spans, flamegraph, cost attribution
and Prometheus metrics (SYSTEM / MODEL / COGNITIVE / BUSINESS families).

Spans follow the OpenTelemetry GenAI semantic conventions (``gen_ai.operation.name``,
``gen_ai.request.model``, ``gen_ai.usage.input_tokens``...) and are exported as OTLP/HTTP
JSON (``/v1/traces``) to any collector - no SDK dependency. HYDRA adds cognitive
semantics on top: confidence before/after, escalations, claims, cost per component.

    Task 4.8s
    ├── routing     0.03s
    ├── retrieving  0.21s
    ├── executing   2.40s   (reasoner, tools)
    ├── verifying   1.20s
    └── synthesizing 0.46s
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict, deque
from typing import Any

import httpx

from hydra.core.events import EventType, HydraEvent

log = logging.getLogger("hydra.tracing")

BUCKETS_MS = (50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 120000)
BUCKETS_PCT = (10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 99, 100)
# Histograms whose unit is not milliseconds get their own buckets (a percentage in ms buckets
# piles every observation into the first two and makes quantiles meaningless).
BUCKETS_BY_METRIC = {"hydra_confidence_pct": BUCKETS_PCT}


def _hex(uuid_like: str, n: int) -> str:
    return uuid_like.replace("-", "")[:n].ljust(n, "0")


class _Span:
    __slots__ = ("name", "span_id", "parent", "start", "end", "attrs", "status")

    def __init__(self, name: str, span_id: str, parent: str | None, start: float, attrs: dict | None = None) -> None:
        self.name, self.span_id, self.parent, self.start = name, span_id, parent, start
        self.end: float | None = None
        self.attrs = attrs or {}
        self.status = "OK"

    def to_otlp(self, trace_id: str) -> dict[str, Any]:
        def val(v):
            if isinstance(v, bool):
                return {"boolValue": v}
            if isinstance(v, int):
                return {"intValue": str(v)}
            if isinstance(v, float):
                return {"doubleValue": v}
            return {"stringValue": str(v)}
        return {"traceId": trace_id, "spanId": self.span_id, **({"parentSpanId": self.parent} if self.parent else {}),
                "name": self.name, "kind": 1, "startTimeUnixNano": str(int(self.start * 1e9)),
                "endTimeUnixNano": str(int((self.end or self.start) * 1e9)),
                "attributes": [{"key": k, "value": val(v)} for k, v in self.attrs.items() if v is not None],
                "status": {"code": 1 if self.status == "OK" else 2}}


class _Trace:
    def __init__(self, task_id: str, start: float) -> None:
        self.task_id = task_id
        self.trace_id = _hex(task_id, 32)
        self.root = _Span("hydra.task", _hex(task_id, 16), None, start, {"hydra.task_id": task_id})
        self.spans: list[_Span] = [self.root]
        self.stage: _Span | None = None
        self.open: dict[str, _Span] = {}
        self.counter = 0
        self.costs: dict[str, float] = defaultdict(float)
        self.done = False

    def new_id(self) -> str:
        self.counter += 1
        return f"{int(self.root.span_id[:8], 16) ^ self.counter:08x}{self.counter:08x}"


class _HistogramMap(dict):
    """defaultdict(Histogram) that picks the buckets from the metric name (key[0])."""

    def __missing__(self, key: tuple) -> Histogram:
        h = self[key] = Histogram(BUCKETS_BY_METRIC.get(key[0], BUCKETS_MS))
        return h


class Histogram:
    def __init__(self, buckets: tuple[float, ...] = BUCKETS_MS) -> None:
        self.buckets = buckets
        self.counts = [0] * (len(buckets) + 1)
        self.sum = 0.0
        self.n = 0

    def observe(self, v: float) -> None:
        self.n += 1
        self.sum += v
        for i, b in enumerate(self.buckets):
            if v <= b:
                self.counts[i] += 1
                return
        self.counts[-1] += 1


class CognitiveTracer:
    def __init__(self, otlp_endpoint: str | None = None, registry=None, keep: int = 500,
                 service_name: str = "hydra") -> None:
        self.endpoint = otlp_endpoint.rstrip("/") if otlp_endpoint else None
        self.registry = registry
        self.service = service_name
        self.active: dict[str, _Trace] = {}
        self.finished: deque[_Trace] = deque(maxlen=keep)
        self.counters: dict[tuple, float] = defaultdict(float)
        self.hist: dict[tuple, Histogram] = _HistogramMap()
        self._pending: list[dict] = []
        self._exports: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ event -> spans/metrics
    async def observe(self, e: HydraEvent) -> None:
        try:
            self._observe(e)
        except Exception:
            log.debug("tracer failed on %s", e.type, exc_info=True)
        if self._pending and self.endpoint:
            batch, self._pending = self._pending, []
            task = asyncio.get_running_loop().create_task(self._export(batch))
            self._exports.add(task)  # the loop keeps only weak references to tasks
            task.add_done_callback(self._exports.discard)

    def _observe(self, e: HydraEvent) -> None:
        tid = str(e.task_id)
        now = e.timestamp.timestamp()
        p = e.payload
        if e.type == EventType.TASK_CREATED:
            t = _Trace(tid, now)
            t.root.attrs.update({"hydra.mode": p.get("mode"), "hydra.private": p.get("private"),
                                 "hydra.shadow": p.get("shadow")})
            self.active[tid] = t
            return
        t = self.active.get(tid)
        if t is None:
            return
        if e.type == EventType.TASK_STATUS:
            if t.stage is not None:
                t.stage.end = now
            st = p.get("status", "")
            t.stage = _Span(f"hydra.stage.{st}", t.new_id(), t.root.span_id, now, {"hydra.stage": st})
            t.spans.append(t.stage)
        elif e.type == EventType.MODEL_STARTED:
            key = f"model:{p.get('model')}:{p.get('role')}:{p.get('attempt', '')}"
            s = _Span(f"chat {p.get('model')}", t.new_id(), (t.stage or t.root).span_id, now, {
                "gen_ai.operation.name": "chat", "gen_ai.request.model": p.get("model"),
                "gen_ai.provider.name": p.get("provider"), "hydra.role": p.get("role")})
            t.open[key] = s
            t.spans.append(s)
        elif e.type in (EventType.MODEL_COMPLETED, EventType.MODEL_FAILED):
            model, role = p.get("model"), p.get("role")
            key = next((k for k in t.open if k.startswith(f"model:{model}:{role}:")), None)
            s = t.open.pop(key) if key else _Span(f"chat {model}", t.new_id(), (t.stage or t.root).span_id,
                                                   now - p.get("latency_ms", 0) / 1000)
            if key is None:
                t.spans.append(s)
            s.end = now
            s.attrs.update({"gen_ai.request.model": model, "gen_ai.usage.input_tokens": p.get("input_tokens"),
                            "gen_ai.usage.output_tokens": p.get("output_tokens"), "hydra.role": role})
            ok = e.type == EventType.MODEL_COMPLETED
            if not ok:
                s.status = "ERROR"
                s.attrs["error.type"] = p.get("kind") or p.get("error", "")[:80]
            lat = float(p.get("latency_ms") or (s.end - s.start) * 1000)
            self.counters[("hydra_model_calls_total", model, role, "ok" if ok else "error")] += 1
            self.hist[("hydra_model_latency_ms", model)].observe(lat)
            self.counters[("hydra_tokens_total", model, "input")] += p.get("input_tokens", 0) or 0
            self.counters[("hydra_tokens_total", model, "output")] += p.get("output_tokens", 0) or 0
            m = self.registry.models.get(model) if self.registry else None
            if m is not None:
                c = m.estimate_cost(p.get("input_tokens", 0) or 0, p.get("output_tokens", 0) or 0)
                t.costs[f"{role}:{model}"] += c
                self.counters[("hydra_cost_eur_total", model)] += c
        elif e.type == EventType.TOOL_STARTED:
            s = _Span(f"execute_tool {p.get('tool')}", t.new_id(), (t.stage or t.root).span_id, now, {
                "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": p.get("tool")})
            t.open[f"tool:{p.get('tool')}"] = s
            t.spans.append(s)
        elif e.type in (EventType.TOOL_COMPLETED, EventType.TOOL_FAILED, EventType.TOOL_DENIED):
            s = t.open.pop(f"tool:{p.get('tool')}", None)
            ok = e.type == EventType.TOOL_COMPLETED and p.get("success", True)
            if s is not None:
                s.end = now
                s.status = "OK" if ok else "ERROR"
            self.counters[("hydra_tool_calls_total", p.get("tool"), "ok" if ok else e.type.value)] += 1
            if p.get("duration_ms"):
                self.hist[("hydra_tool_latency_ms", p.get("tool"))].observe(float(p["duration_ms"]))
        elif e.type == EventType.VERIFICATION_COMPLETED:
            t.root.attrs["hydra.confidence_before"] = t.root.attrs.get("hydra.confidence_after")
            t.root.attrs["hydra.confidence_after"] = p.get("confidence")
            t.root.attrs["hydra.verified"] = p.get("verified")
        elif e.type == EventType.ESCALATED:
            self.counters[("hydra_escalations_total",)] += 1
        elif e.type == EventType.CACHE_HIT:
            self.counters[("hydra_cache_hits_total",)] += 1
        elif e.type == EventType.ROUTE_SELECTED:
            t.root.attrs.update({"hydra.task_type": p.get("task_type"), "hydra.complexity": p.get("complexity"),
                                 "hydra.arm": p.get("arm")})
        elif e.type in (EventType.TASK_COMPLETED, EventType.TASK_FAILED):
            if t.stage is not None:
                t.stage.end = now
            t.root.end = now
            ok = e.type == EventType.TASK_COMPLETED
            t.root.status = "OK" if ok else "ERROR"
            if p.get("confidence") is not None:
                self.hist[("hydra_confidence_pct",)].observe(float(p["confidence"]) * 100)
            self.counters[("hydra_tasks_total", "completed" if ok else "failed")] += 1
            self.hist[("hydra_task_latency_ms",)].observe((t.root.end - t.root.start) * 1000)
            for s in t.spans:
                if s.end is None:
                    s.end = now
            t.done = True
            self.finished.append(t)
            self.active.pop(tid, None)
            if self.endpoint:
                self._pending.extend(s.to_otlp(t.trace_id) for s in t.spans)

    async def _export(self, spans: list[dict]) -> None:
        body = {"resourceSpans": [{"resource": {"attributes": [
            {"key": "service.name", "value": {"stringValue": self.service}}]},
            "scopeSpans": [{"scope": {"name": "hydra.cognitive"}, "spans": spans}]}]}
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                await c.post(f"{self.endpoint}/v1/traces", json=body)
        except Exception:
            log.debug("OTLP export failed", exc_info=True)

    # ------------------------------------------------------------------ views
    def _find(self, task_id: str) -> _Trace | None:
        return self.active.get(task_id) or next((t for t in self.finished if t.task_id == task_id), None)

    def flamegraph(self, task_id: str) -> dict[str, Any] | None:
        t = self._find(task_id)
        if t is None:
            return None
        children: dict[str, list[_Span]] = defaultdict(list)
        for s in t.spans[1:]:
            children[s.parent or ""].append(s)

        def node(s: _Span) -> dict:
            return {"name": s.name, "ms": round(((s.end or time.time()) - s.start) * 1000, 1), "status": s.status,
                    "attributes": {k: v for k, v in s.attrs.items() if v is not None},
                    "children": [node(c) for c in sorted(children.get(s.span_id, []), key=lambda x: x.start)]}
        return node(t.root)

    def cost_attribution(self, task_id: str | None = None) -> dict[str, float]:
        if task_id:
            t = self._find(task_id)
            return {k: round(v, 6) for k, v in (t.costs if t else {}).items()}
        out: dict[str, float] = defaultdict(float)
        for t in self.finished:
            for k, v in t.costs.items():
                out[k.split(":")[0]] += v
        return {k: round(v, 6) for k, v in out.items()}

    def stage_profile(self) -> dict[str, float]:
        """Mean ms per stage over recent tasks: where HYDRA loses time."""
        acc: dict[str, list[float]] = defaultdict(list)
        for t in self.finished:
            for s in t.spans:
                if s.name.startswith("hydra.stage.") and s.end:
                    acc[s.name[12:]].append((s.end - s.start) * 1000)
        return {k: round(sum(v) / len(v), 1) for k, v in acc.items()}

    # ------------------------------------------------------------------ prometheus
    def prometheus(self, gauges: dict[str, float] | None = None) -> str:
        lines: list[str] = []
        by_name: dict[str, list[tuple[tuple, float]]] = defaultdict(list)
        for key, v in self.counters.items():
            by_name[key[0]].append((key[1:], v))
        label_names = {"hydra_model_calls_total": ("model", "role", "status"), "hydra_tokens_total": ("model", "kind"),
                       "hydra_tool_calls_total": ("tool", "status"), "hydra_tasks_total": ("status",),
                       "hydra_cost_eur_total": ("model",)}
        for name, rows in sorted(by_name.items()):
            lines.append(f"# TYPE {name} counter")
            for labels, v in rows:
                names = label_names.get(name, ())
                lab = ",".join(f'{n}="{str(x).replace(chr(34), "")}"' for n, x in zip(names, labels))
                lines.append(f"{name}{{{lab}}} {v}" if lab else f"{name} {v}")
        for key, h in sorted(self.hist.items(), key=lambda kv: kv[0]):
            name, extra = key[0], key[1:]
            lab = f'model="{extra[0]}",' if extra and name == "hydra_model_latency_ms" else \
                f'tool="{extra[0]}",' if extra else ""
            lines.append(f"# TYPE {name} histogram")
            cum = 0
            for b, c in zip(h.buckets, h.counts):
                cum += c
                lines.append(f'{name}_bucket{{{lab}le="{b}"}} {cum}')
            lines.append(f'{name}_bucket{{{lab}le="+Inf"}} {h.n}')
            lines.append(f"{name}_sum{{{lab.rstrip(',')}}} {round(h.sum, 3)}" if lab else f"{name}_sum {round(h.sum, 3)}")
            lines.append(f"{name}_count{{{lab.rstrip(',')}}} {h.n}" if lab else f"{name}_count {h.n}")
        for k, v in sorted((gauges or {}).items()):
            lines.append(f"# TYPE {k} gauge")
            lines.append(f"{k} {v}")
        lines.append("# TYPE hydra_process_pid gauge")
        lines.append(f"hydra_process_pid {os.getpid()}")
        return "\n".join(lines) + "\n"
