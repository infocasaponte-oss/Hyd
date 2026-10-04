# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA OS endpoints: provenance, artifacts, system status, policy, evals, Lab and Model Factory.
The Factory endpoints only enqueue jobs: inference never builds models."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from hydra.api.security import authorize_admin
from hydra.blackboard.projector import replay
from hydra.evals.engine import apply_to_registry
from hydra.lab.lab import Gates
from hydra.model_factory.hardware import detect_local
from hydra.model_factory.store import ResolveConstraints
from hydra.router.learned import ABRouter

FACTORY_JOBS = {"import", "build", "evaluate", "optimize", "canary", "distill", "train", "jit"}


class ClassifyBody(BaseModel):
    text: str


class EvalBody(BaseModel):
    model_id: str
    suites: list[str] | None = None
    apply: bool = False


class ExperimentBody(BaseModel):
    name: str
    kind: str = "config"
    overrides: dict[str, Any]
    description: str = ""
    gates: Gates | None = None


class JobBody(BaseModel):
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)


def register_os_routes(app: FastAPI, rt, secured, admin_secured=None) -> None:
    admin_secured = admin_secured if admin_secured is not None else secured
    async def _state(request: Request, task_id: UUID):
        runtime = rt(request)
        events = (await runtime.event_sink.history(task_id) if runtime.event_sink is not None
                  else await runtime.bus.history(task_id))
        if not events:
            raise HTTPException(404, "task not found")
        return replay(events)

    # ------------------------------------------------------------------ task introspection
    @app.get("/v1/tasks/{task_id}/provenance", dependencies=secured)
    async def provenance(task_id: UUID, request: Request):
        return (await _state(request, task_id)).provenance

    @app.get("/v1/tasks/{task_id}/artifacts", dependencies=secured)
    async def artifacts(task_id: UUID, request: Request):
        return (await _state(request, task_id)).artifacts

    @app.get("/v1/tasks/{task_id}/claims", dependencies=secured)
    async def claims(task_id: UUID, request: Request):
        s = await _state(request, task_id)
        return {"claims": s.claims, "world": s.world, "counterfactual": s.counterfactual,
                "research_graph": s.research_graph, "simulations": s.simulations}

    # ------------------------------------------------------------------ system status
    @app.get("/v1/os/status", dependencies=secured)
    async def os_status(request: Request):
        runtime = rt(request)
        runs = await runtime.telemetry.recent_runs()
        k = runtime.kernel
        return {
            "config": k.config.model_dump(mode="json"),
            "runtime": runtime.monitor.snapshot() if runtime.monitor else None,
            "semantic_cache": {"entries": len(runtime.cache.entries)},
            "failure_memory": runtime.failures.report()[:50],
            "counterfactual": k.counterfactual_stats.summary(),
            "learned_router": {"ready": k.learned.ready(), "samples": k.learned.samples,
                               "ab": [a.model_dump() for a in ABRouter.report(runs)]},
            "breakers": {m: {"open": s.open, "failures": s.failures}
                         for m, s in runtime.registry.breaker.models.items()},
        }

    @app.post("/v1/os/cache/invalidate", dependencies=admin_secured)
    async def invalidate(request: Request):
        return {"invalidated": rt(request).cache.invalidate()}

    # ------------------------------------------------------------------ policy
    @app.get("/v1/policy", dependencies=secured)
    async def policy(request: Request):
        r = rt(request).policy.rules
        return {"local_only_at": r.local_only_at.name.lower(), "cloud_clearance": r.cloud_clearance.name.lower(),
                "forbidden_tools": sorted(r.forbidden_tools), "confirm_tools": sorted(r.confirm_tools),
                "confirm_risk_level": r.confirm_risk_level,
                "patterns": sorted([*r.secret_patterns, *r.confidential_patterns])}

    @app.post("/v1/policy/classify", dependencies=secured)
    async def classify(body: ClassifyBody, request: Request):
        pk = rt(request).policy
        level, findings = pk.classify(body.text)
        return {"sensitivity": level.name.lower(), "findings": sorted({f.kind for f in findings}),
                "redacted": pk.redact(body.text)}

    # ------------------------------------------------------------------ evals
    @app.post("/v1/evals/run", dependencies=secured)
    async def run_eval(body: EvalBody, request: Request):
        runtime = rt(request)
        if body.apply:  # applying scores changes routing for everyone: operator decision
            authorize_admin(runtime.settings, request.client.host if request.client else "",
                            request.headers.get("x-hydra-admin-token"))
        if body.model_id not in runtime.registry.models:
            raise HTTPException(404, "unknown model")
        report = await runtime.evaluator.run_model(runtime.registry.get(body.model_id), body.suites)
        if body.apply:
            apply_to_registry(report, runtime.registry)
        return report

    # ------------------------------------------------------------------ lab
    @app.get("/v1/lab/experiments", dependencies=secured)
    async def experiments(request: Request):
        return list(rt(request).lab.experiments.values())

    @app.post("/v1/lab/experiments", dependencies=admin_secured)
    async def create_experiment(body: ExperimentBody, request: Request):
        try:
            return rt(request).lab.create(body.name, body.kind, body.overrides, body.description, body.gates)
        except Exception as exc:
            raise HTTPException(400, f"invalid overrides: {exc}") from exc

    @app.post("/v1/lab/experiments/{exp_id}/{action}", dependencies=admin_secured)
    async def experiment_action(exp_id: str, action: str, request: Request):
        lab = rt(request).lab
        if exp_id not in lab.experiments:
            raise HTTPException(404, "unknown experiment")
        match action:
            case "benchmark":
                return await lab.run_benchmark(exp_id)
            case "shadow":
                return lab.start_shadow(exp_id)
            case "promote":
                return lab.promote(exp_id)
            case "rollback":
                return lab.rollback(exp_id)
        raise HTTPException(400, "action must be benchmark | shadow | promote | rollback")

    # ------------------------------------------------------------------ model factory
    @app.get("/v1/factory/status", dependencies=secured)
    async def factory_status(request: Request):
        return rt(request).factory.status()

    @app.get("/v1/factory/hardware", dependencies=secured)
    async def hardware():
        return detect_local()

    @app.get("/v1/factory/variants", dependencies=secured)
    async def variants(request: Request, logical: str | None = None):
        store = rt(request).factory.store
        return [v for v in store.variants.values() if logical is None or v.logical_model == logical]

    @app.get("/v1/factory/artifacts/{artifact_id}/lineage", dependencies=secured)
    async def lineage(artifact_id: str, request: Request):
        store = rt(request).factory.store
        if artifact_id not in store.artifacts:
            raise HTTPException(404, "unknown artifact")
        return {"artifact": store.artifacts[artifact_id], "lineage": store.ancestry(artifact_id)}

    @app.get("/v1/factory/resolve/{logical}", dependencies=secured)
    async def resolve(logical: str, request: Request, quality: float | None = None,
                      max_memory_gb: float | None = None, local: bool | None = None):
        v = rt(request).factory.resolve(logical, ResolveConstraints(quality=quality, max_memory_gb=max_memory_gb,
                                                                    local=local))
        if v is None:
            raise HTTPException(404, "no variant satisfies the constraints")
        return v

    @app.post("/v1/factory/jobs", dependencies=admin_secured, status_code=202)
    async def submit_job(body: JobBody, request: Request):
        if body.kind not in FACTORY_JOBS:
            raise HTTPException(400, f"kind must be one of {sorted(FACTORY_JOBS)}")
        return rt(request).factory.submit(body.kind, body.params)

    @app.get("/v1/factory/jobs/{job_id}", dependencies=secured)
    async def get_job(job_id: str, request: Request):
        store = rt(request).factory.store
        store.reload_jobs()
        if job_id not in store.jobs:
            raise HTTPException(404, "unknown job")
        return store.jobs[job_id]
