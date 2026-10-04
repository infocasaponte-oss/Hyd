# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Replay Engine, digital trace replay and the Autonomous Improvement Laboratory.

    hydra replay TASK --mode audit          reconstruct what happened (events + flight recorder + ledger)
    hydra replay TASK --mode simulation     re-run the decision flow without side effects (shadow)
    hydra replay TASK --replace-model a=b   counterfactual: same state, different model/policy
    hydra replay --traces 30 --config c.json   estimate routing/cost/latency changes over history

Production never modifies itself: the lab only *proposes* improvements (HYDRA-IMP-n) that
go through benchmark -> shadow -> canary like any other change."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from hydra.blackboard.projector import replay as project
from hydra.core.contracts import HydraRequest, RoutingDecision
from hydra.core.hashing import canonical_json, now_iso, sha256_hex
from hydra.verification.consensus import pair_agreement


class ReplayReport(BaseModel):
    task_id: str
    mode: str
    original: dict[str, Any] = Field(default_factory=dict)
    replayed: dict[str, Any] = Field(default_factory=dict)
    agreement: float | None = None
    integrity: dict[str, Any] = Field(default_factory=dict)
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    diff: dict[str, Any] = Field(default_factory=dict)


class ReplayEngine:
    def __init__(self, runtime) -> None:
        self.rt = runtime

    async def _task(self, task_id: str):
        t = await self.rt.telemetry.get_task(UUID(task_id))
        if t is None or not t.request:
            raise KeyError(f"task {task_id} not found")
        return t

    def _flight(self, task_id: str) -> dict[str, Any] | None:
        p = self.rt.settings.data_dir / "flight" / f"{task_id}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    async def audit(self, task_id: str) -> ReplayReport:
        events = await self.rt.bus.history(UUID(task_id))
        state = project(events)
        flight = self._flight(task_id)
        integrity: dict[str, Any] = {"flight_recorder": flight is not None}
        if flight:
            body = {k: v for k, v in flight.items() if k != "manifest_hash"}
            integrity["manifest_hash_ok"] = sha256_hex(canonical_json(body)) == flight.get("manifest_hash")
            ledger = [e for e in self.rt.ledger.for_object("task", task_id) if e.event_type == "TASK_EXECUTED"]
            integrity["ledger_event"] = ledger[-1].sequence if ledger else None
            integrity["ledger_matches"] = bool(ledger) and ledger[-1].payload.get("manifest_hash") == flight.get(
                "manifest_hash")
            live = [{"type": e.type.value, "hash": sha256_hex(canonical_json(e.payload))} for e in events]
            rec = [{"type": x["type"], "hash": x["hash"]} for x in flight.get("events", [])]
            integrity["events_match_recording"] = live[:len(rec)] == rec if live else None
        timeline = [{"t": e.timestamp.isoformat(), "type": e.type.value, "source": e.source} for e in events]
        return ReplayReport(task_id=task_id, mode="audit", integrity=integrity, timeline=timeline,
                            original={"status": state.status, "answer": state.final_answer,
                                      "models": state.models_used, "tools": state.tools_used,
                                      "verification": state.verification, "world": flight.get("world_version_after")
                                      if flight else None})

    async def rerun(self, task_id: str, *, replace_models: dict[str, str] | None = None,
                    config: dict[str, Any] | None = None) -> ReplayReport:
        t = await self._task(task_id)
        req = HydraRequest.model_validate(t.request).model_copy(update={"use_cache": False})
        overrides = dict(config or {})
        if replace_models:
            overrides["disabled_models"] = set(overrides.get("disabled_models", set())) | set(replace_models)
            overrides["enabled_models"] = set(overrides.get("enabled_models", set())) | set(replace_models.values())
        kernel = self.rt.kernel.with_config(**overrides) if overrides else self.rt.kernel
        resp = await kernel.run(req, shadow=True, learn=False)  # no side effects, no learning
        fr = t.final_response or {}
        om = fr.get("meta") or {}
        mode = "counterfactual" if overrides else "simulation"
        orig = {"answer": fr.get("answer"), "models": om.get("models_used"), "latency_ms": om.get("latency_ms"),
                "confidence": om.get("confidence"), "verified": om.get("verified")}
        new = {"answer": resp.answer, "models": resp.meta.models_used, "latency_ms": resp.meta.latency_ms,
               "confidence": resp.meta.confidence, "verified": resp.meta.verified}
        agree = pair_agreement(orig["answer"] or "", new["answer"] or "") if orig["answer"] else None
        diff = {k: {"old": orig.get(k), "new": new.get(k)} for k in ("models", "latency_ms", "confidence", "verified")
                if orig.get(k) != new.get(k)}
        return ReplayReport(task_id=task_id, mode=mode, original=orig, replayed=new, agreement=agree, diff=diff)


class TraceReplayReport(BaseModel):
    tasks: int
    changed_primary: int
    by_change: dict[str, int] = Field(default_factory=dict)
    predicted_latency_ms: dict[str, float] = Field(default_factory=dict)
    predicted_cost: dict[str, float] = Field(default_factory=dict)
    preference_examples: list[dict[str, Any]] = Field(default_factory=list)


def replay_traces(runtime, tasks: list, candidate: dict[str, Any]) -> TraceReplayReport:
    """Digital replay: recompute the model ranking of past tasks under a candidate configuration,
    without calling any model; estimate latency/cost changes from registry statistics."""
    reg = runtime.registry
    base_cfg = runtime.kernel.config
    cand_kernel = runtime.kernel.with_config(**candidate)
    changed, by, lat, cost = 0, {}, {"current": 0.0, "candidate": 0.0}, {"current": 0.0, "candidate": 0.0}
    prefs = []
    n = 0
    for t in tasks:
        if not t.request or not t.route:
            continue
        try:
            req = HydraRequest.model_validate(t.request)
            route = RoutingDecision.model_validate(t.route)
        except Exception:
            continue

        class _Ctx:
            pass
        ctx = _Ctx()
        ctx.request, ctx.sensitivity = req, 0
        cur = [m for m in reg.select(req, route) if m.id not in base_cfg.disabled_models]
        new = [m for m in reg.select(req, route) if m.id not in cand_kernel.config.disabled_models]
        extra = [m for m in reg.all() if m.id in cand_kernel.config.enabled_models and m not in new]
        new = extra + new
        if not cur or not new:
            continue
        n += 1
        a, b = cur[0], new[0]
        lat["current"] += a.predicted_latency_ms
        lat["candidate"] += b.predicted_latency_ms
        cost["current"] += a.estimate_cost(1000, 500)
        cost["candidate"] += b.estimate_cost(1000, 500)
        if a.id != b.id:
            changed += 1
            key = f"{a.id}->{b.id}"
            by[key] = by.get(key, 0) + 1
            qa, qb = a.quality(route.task_type), b.quality(route.task_type)
            if abs(qa - qb) <= 0.03:
                cheaper = b if b.predicted_latency_ms < a.predicted_latency_ms else a
                prefs.append({"query": req.last_user_text[:500], "chosen": cheaper.id,
                              "rejected": (a if cheaper is b else b).id, "reason": "equal quality, faster"})
    return TraceReplayReport(tasks=n, changed_primary=changed, by_change=by,
                             predicted_latency_ms={k: round(v / max(1, n), 1) for k, v in lat.items()},
                             predicted_cost={k: round(v, 6) for k, v in cost.items()}, preference_examples=prefs[:200])


class ImprovementProposal(BaseModel):
    id: str
    observation: str
    cluster: str
    proposal: str
    projected: dict[str, float]
    status: str = "LAB_CANDIDATE"
    created_at: str = Field(default_factory=now_iso)


class ImprovementLab:
    """Discover weakness -> propose improvement (never apply it): the Autonomous Improvement Laboratory."""

    def __init__(self, runtime) -> None:
        from hydra.core.docstore import DocumentStore

        self.rt = runtime
        self.path = runtime.settings.data_dir / "improvements.json"
        self._doc = (getattr(runtime, "documents", None) or DocumentStore()).document(
            "improvements.json", self.path, default=list)

    def load(self) -> list[ImprovementProposal]:
        return [ImprovementProposal(**x) for x in self._doc.get()]

    async def analyze(self) -> list[ImprovementProposal]:
        """Telemetry is read first; the proposals are then derived on the latest stored list with the
        document locked, so two nodes analysing at once never mint the same HYDRA-IMP id."""
        runs = await self.rt.telemetry.recent_runs()
        holder: dict[str, list[ImprovementProposal]] = {}

        def apply(rows: list) -> list:
            holder["props"] = self._propose(runs, [ImprovementProposal(**x) for x in rows])
            return [p.model_dump() for p in holder["props"]]

        self._doc.update(apply)
        return holder["props"]

    def _propose(self, runs, props: list[ImprovementProposal]) -> list[ImprovementProposal]:
        by_role: dict[str, float] = {}
        by_model_role: dict[tuple, list] = {}
        for r in runs:
            by_role[r.role] = by_role.get(r.role, 0.0) + (r.latency_ms or 0)
            by_model_role.setdefault((r.model_id, r.role, r.task_type), []).append(r)
        total = sum(by_role.values()) or 1.0
        for (model, role, ttype), rs in by_model_role.items():
            share = sum(x.latency_ms or 0 for x in rs) / total
            if role in ("critic", "judge", "router", "claim_verifier") and share >= 0.15 and len(rs) >= 20:
                pid = f"HYDRA-IMP-{len(props) + 1:03d}"
                if any(p.cluster == f"{role}:{ttype}" for p in props):
                    continue
                props.append(ImprovementProposal(
                    id=pid, observation=f"{model} as {role} consumes {share:.1%} of inference compute",
                    cluster=f"{role}:{ttype}",
                    proposal=f"distill HYDRA-{ttype.title()}-{role.title()}-1.5B from verified {role} traces",
                    projected={"compute": round(-share * 0.66, 4), "latency": round(-share * 0.4, 4),
                               "quality_delta_max": 0.005}))
        fails = [r for r in runs if not r.success]
        if runs and len(fails) / len(runs) > 0.1:
            props.append(ImprovementProposal(
                id=f"HYDRA-IMP-{len(props) + 1:03d}", observation=f"{len(fails) / len(runs):.1%} model calls fail",
                cluster="reliability", proposal="lower priority of failing models / add fallback variant (quant)",
                projected={"failure_rate": round(-len(fails) / len(runs) * 0.5, 4)}))
        return props
