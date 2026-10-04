# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA 1.0 platform API: native protocol, MCP, OpenAI Responses/Embeddings, WebSocket events,
World Model, Corpus, IP/Licenses/Releases, Cluster/Fabric, Training, Governance, Replay,
Observability, Edge/Translation and the Studio UI."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from hydra.api.security import authenticate, authorize_admin, websocket_token
from hydra.core.contracts import ExecutionMode, HydraRequest, Message
from hydra.core.kernel import HydraTaskFailed
from hydra.core.paths import PathNotAllowed, confine, safe_id
from hydra.core.task import EventEnvelope, HydraResult, HydraTask
from hydra.core.request_budget import RequestBudgetExceeded as BudgetExceeded

log = logging.getLogger("hydra.api")
MAX_JOBS = 500
# The Studio keeps the API key in the browser: it may only talk to this origin, never be framed.
STUDIO_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                               "img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; "
                               "base-uri 'none'; form-action 'self'; object-src 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


# ------------------------------------------------------------------------------ bodies
class GoalBody(BaseModel):
    goal: str = Field(min_length=1, max_length=20_000)
    workspace: str | None = None
    mode: str = "balanced"
    authorized: list[str] = Field(default_factory=list, max_length=64)
    """Capabilities/action ids explicitly authorized for this goal (requires the admin token)."""
    max_seconds: float = Field(default=600, gt=0, le=3600)


class ResponsesBody(BaseModel):
    model: str = "hydra"
    input: str | list[dict[str, Any]]
    instructions: str | None = None


class EmbeddingsBody(BaseModel):
    model: str = "hydra-embed"
    input: str | list[str]


class WorldQueryBody(BaseModel):
    query: str | None = None
    subject: str | None = None
    predicate: str | None = None
    at: str | None = None
    depth: int = 1


class CorpusQueryBody(BaseModel):
    text: str | None = None
    record_type: str | None = None
    domain: str | None = None
    language: str | None = None
    capability: str | None = None
    min_quality: float = 0.0
    statuses: list[str] | None = None
    limit: int = 50


class ReviewBody(BaseModel):
    approve: bool
    reviewer: str
    training_allowed: bool | None = None


class ReasonBody(BaseModel):
    reason: str


class InventionBody(BaseModel):
    title: str
    problem: str = ""
    solution: str = ""
    mechanism: str = ""
    previous_approach: str = ""
    features: list[str] = Field(default_factory=list)
    contributors: list[str] = Field(default_factory=list)
    family: str | None = None


class StatusBody(BaseModel):
    status: str
    actor: str
    reason: str = ""


class EffectBody(BaseModel):
    metric: str
    baseline_value: float
    experimental_value: float
    unit: str = ""
    lower_is_better: bool = True
    experiment_id: str = ""


class LicenseEvalBody(BaseModel):
    target: str
    components: list[dict[str, Any] | str]


class ReleaseBody(BaseModel):
    name: str
    components: dict[str, str] = Field(default_factory=dict)
    eval_results: dict[str, Any] = Field(default_factory=dict)


class GateBody(BaseModel):
    artifact: dict[str, Any]
    target: str


class ResolveBody(BaseModel):
    capability: str
    constraints: dict[str, Any] = Field(default_factory=dict)


class LifecycleBody(BaseModel):
    to: str
    reason: str
    actor: str = "api"


class PlaceBody(BaseModel):
    task_type: str = "chat"
    mode: str = "balanced"
    private: bool = False
    prompt_chars: int = 2000
    expected_output_tokens: int = 300
    sla: str = "interactive"
    conversation_id: str | None = None


class WorkBody(BaseModel):
    capability: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: str = "normal"
    idempotency_key: str = ""
    timeout_ms: int = 120_000


class FlagBody(BaseModel):
    value: str
    description: str = ""


class ConfigBody(BaseModel):
    values: dict[str, Any]
    author: str = "api"
    message: str = ""


class PolicyEvalBody(BaseModel):
    facts: dict[str, Any]


class ReplayBody(BaseModel):
    mode: str = "audit"  # audit | simulation | counterfactual
    replace_models: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class TranslateBody(BaseModel):
    text: str
    target_language: str
    source_language: str | None = None
    glossary: dict[str, str] = Field(default_factory=dict)
    glossary_name: str | None = Field(default=None, validation_alias=AliasChoices("glossary_name", "glossary_id"))
    domain: str = "general"
    model: str | None = None


class GlossaryBody(BaseModel):
    terms: dict[str, str]


class AutobuildBody(BaseModel):
    model: str
    runtime: str = "ollama"
    apply: bool = False


class SyncImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")  # trust is server configuration, never request data
    bundle: dict[str, Any]


class FederatedCountBody(BaseModel):
    local_counts: dict[str, int]
    min_count: int = 5
    differential_privacy: bool = False


class TrainingBody(BaseModel):
    recipe: dict[str, Any]
    dataset: dict[str, Any] | None = None


def register_platform_routes(app: FastAPI, rt, secured, admin_secured=None) -> None:  # noqa: C901 - route table
    admin_secured = admin_secured if admin_secured is not None else secured
    jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
    running: set[asyncio.Task] = set()

    def _spawn(kind: str, coro) -> dict[str, Any]:
        jid = f"{kind}-{uuid4().hex[:8]}"
        jobs[jid] = {"id": jid, "kind": kind, "status": "running", "started": time.time()}

        async def run():
            try:
                res = await coro
                jobs[jid].update(status="done", result=json.loads(json.dumps(
                    res.model_dump(mode="json") if hasattr(res, "model_dump") else res, default=str)))
            except Exception as exc:
                jobs[jid].update(status="failed", error=f"{type(exc).__name__}: {exc}"[:500])
        while len(jobs) > MAX_JOBS:  # bounded history: drop the oldest finished jobs first
            oldest = next((k for k, v in jobs.items() if v["status"] != "running"), None)
            if oldest is None:
                break
            jobs.pop(oldest)
        task = asyncio.get_running_loop().create_task(run())
        running.add(task)  # keep a reference: the event loop only holds weak references to tasks
        task.add_done_callback(running.discard)
        return jobs[jid]

    @app.get("/hydra/v1/jobs/{job_id}", dependencies=secured)
    async def job(job_id: str):
        if job_id not in jobs:
            raise HTTPException(404, "unknown job")
        return jobs[job_id]

    # ================================================================== native tasks / goals
    async def _run_task(request: Request, task: HydraTask) -> HydraResult:
        runtime = rt(request)
        tenant = task.security_context.tenant_id
        ok, why = runtime.tenants.check(tenant) if tenant else (True, "")
        if not ok:
            raise HTTPException(403, why)
        try:
            resp = await runtime.lab.serve(task.to_request(), task_id=task.id)
        except HydraTaskFailed as exc:
            raise HTTPException(502, {"task_id": str(exc.task_id), "kind": exc.kind,
                                      "error": exc.public_message()}) from exc
        return HydraResult.from_response(resp)

    @app.post("/v1/tasks", response_model=HydraResult, dependencies=secured)
    async def create_task(task: HydraTask, request: Request):
        return await _run_task(request, task)

    @app.post("/hydra/v1/tasks", response_model=HydraResult, dependencies=secured)
    async def create_task_native(task: HydraTask, request: Request):
        return await _run_task(request, task)

    @app.post("/hydra/v1/goals", dependencies=secured)
    async def run_goal(body: GoalBody, request: Request):
        runtime = rt(request)
        if body.authorized:
            # Explicit authorizations unlock high-risk actions: they are an operator decision,
            # never something the requester grants to itself with the ordinary API key.
            authorize_admin(runtime.settings, request.client.host if request.client else "",
                            request.headers.get("x-hydra-admin-token"))
        ws = None
        if body.workspace:
            try:  # clients name a repository below HYDRA_REPOSITORIES_ROOT, never a host path
                ws = confine(runtime.settings.repositories_root, body.workspace)
            except PathNotAllowed as exc:
                raise HTTPException(403, str(exc)) from exc
            if not ws.is_dir():
                raise HTTPException(400, f"workspace not found: {body.workspace}")
        g = await runtime.goals.run(body.goal, workspace=ws, mode=body.mode, authorized=set(body.authorized),
                                    max_seconds=body.max_seconds)
        return json.loads(g.model_dump_json())

    @app.get("/hydra/v1/goals/{goal_id}", dependencies=secured)
    async def goal_checkpoint(goal_id: str, request: Request):
        st = rt(request).goals.resume_state(goal_id)
        if st is None:
            raise HTTPException(404, "unknown goal")
        return st

    @app.websocket("/v1/ws/tasks")
    async def ws_tasks(websocket: WebSocket):
        runtime = websocket.app.state.runtime
        protocols = [p.strip() for p in websocket.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
        try:  # same policy as HTTP: key required, or loopback-only when no key is configured
            identity = authenticate(runtime.settings, websocket.client.host if websocket.client else "",
                                    websocket_token(websocket.headers, protocols))
            if identity.startswith('client:'):
                raise HTTPException(403, 'client keys do not allow task WebSockets')
        except HTTPException:
            await websocket.close(code=4401)
            return
        await websocket.accept(subprotocol="hydra.v1" if "hydra.v1" in protocols else None)
        listeners = websocket.app.state.listeners
        limiter = getattr(websocket.app.state, "rate_limiter", None)
        try:
            while True:
                data = await websocket.receive_json()
                if limiter is not None:
                    try:
                        limiter.check(identity, runtime.settings.api_rate_limit_per_minute, 60.0)
                    except HTTPException as exc:
                        await websocket.send_json({"type": "error", "kind": "rate_limit", "error": str(exc.detail)})
                        continue
                try:
                    task = HydraTask.model_validate(data)
                except ValueError as exc:
                    await websocket.send_json({"type": "error", "kind": "invalid_request", "error": str(exc)[:500]})
                    continue
                tenant = task.security_context.tenant_id
                ok, why = runtime.tenants.check(tenant) if tenant else (True, "")
                if not ok:
                    await websocket.send_json({"type": "error", "kind": "forbidden", "error": why})
                    continue
                q: asyncio.Queue = asyncio.Queue()
                listeners.queues[task.id] = q
                run = asyncio.create_task(runtime.lab.serve(task.to_request(), task_id=task.id))
                seq = 0
                while True:
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=0.25)
                        seq += 1
                        await websocket.send_json({"type": "event", **EventEnvelope.wrap(ev, seq).model_dump(mode="json")})
                    except asyncio.TimeoutError:
                        if run.done():
                            break
                listeners.queues.pop(task.id, None)
                try:
                    resp = run.result()
                    await websocket.send_json({"type": "result", **HydraResult.from_response(resp).model_dump(mode="json")})
                except HydraTaskFailed as exc:
                    await websocket.send_json({"type": "error", "kind": exc.kind, "error": exc.public_message()})
                except Exception:
                    log.exception("websocket task failed")
                    await websocket.send_json({"type": "error", "error": "the task failed"})
        except WebSocketDisconnect:
            return

    # ================================================================== protocols
    @app.post("/v1/responses", dependencies=secured)
    async def responses(body: ResponsesBody, request: Request):
        msgs = [Message(role="user", content=body.input)] if isinstance(body.input, str) else [
            Message(role=m.get("role", "user"), content=m["content"] if isinstance(m.get("content"), str) else
                    " ".join(p.get("text", "") for p in m.get("content", []) if isinstance(p, dict)))
            for m in body.input]
        if body.instructions:
            msgs.insert(0, Message(role="system", content=body.instructions))
        try:  # same model naming as /v1/chat/completions: hydra, hydra-fast, hydra-deep, hydra-max, hydra-private
            mode = ExecutionMode(body.model.removeprefix("hydra").strip("-") or "balanced")
        except ValueError:
            raise HTTPException(400, f"unknown model '{body.model}'; use hydra, hydra-fast, hydra-deep, "
                                     "hydra-max or hydra-private") from None
        try:
            resp = await rt(request).lab.serve(HydraRequest(messages=msgs, mode=mode))
        except HydraTaskFailed as exc:
            code = 503 if exc.kind in ("unavailable", "rate_limit", "timeout") else 502
            raise HTTPException(code, {"task_id": str(exc.task_id), "kind": exc.kind,
                                       "error": exc.public_message()}) from exc
        return {"id": f"resp_{resp.meta.task_id.replace('-', '')}", "object": "response", "created_at": int(time.time()),
                "model": body.model, "status": "completed",
                "output": [{"type": "message", "id": f"msg_{uuid4().hex[:16]}", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": resp.answer, "annotations": []}]}],
                "output_text": resp.answer,
                "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
                "hydra": {"confidence": resp.meta.confidence, "verified": resp.meta.verified,
                          "task_id": resp.meta.task_id}}

    @app.post("/v1/embeddings", dependencies=secured)
    async def embeddings(body: EmbeddingsBody, request: Request):
        texts = [body.input] if isinstance(body.input, str) else body.input
        vecs = await rt(request).embedder.embed(texts)
        return {"object": "list", "model": body.model,
                "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vecs)],
                "usage": {"prompt_tokens": sum(len(t) // 4 for t in texts), "total_tokens": sum(len(t) // 4 for t in texts)}}

    @app.post("/mcp", dependencies=secured)
    async def mcp(request: Request):
        from hydra.protocols.mcp import MCPServer

        runtime = rt(request)
        server = getattr(runtime, "_mcp", None) or MCPServer(runtime)
        runtime._mcp = server
        body = await request.json()
        if isinstance(body, list):
            out = [r for r in [await server.handle(m) for m in body] if r is not None]
            return JSONResponse(out)
        resp = await server.handle(body)
        return JSONResponse(resp) if resp is not None else JSONResponse(None, status_code=202)

    # ================================================================== world model
    @app.get("/hydra/v1/world", dependencies=secured)
    async def world(request: Request):
        return rt(request).world.stats()

    @app.post("/hydra/v1/world/query", dependencies=secured)
    async def world_query(body: WorldQueryBody, request: Request):
        w = rt(request).world
        if body.query:
            return rt(request).world_rag.packet(body.query, depth=body.depth, at=body.at).model_dump(mode="json")
        sid = None
        if body.subject:
            ent = w.lookup(body.subject)
            sid = ent.id if ent else body.subject
        rels = w.current_relations(sid, body.predicate, at=body.at)
        return {"relations": [r.model_dump() for r in rels],
                "beliefs": [b.model_dump() for b in (w.beliefs_about(body.subject, body.predicate) if body.subject
                                                     else [])]}

    @app.get("/hydra/v1/world/entities/{entity_id:path}/neighbors", dependencies=secured)
    async def neighbors(entity_id: str, request: Request, depth: int = 1):
        return rt(request).world.neighbors(entity_id, depth)

    @app.get("/hydra/v1/world/conflicts", dependencies=secured)
    async def conflicts(request: Request):
        return [[b.model_dump() for b in g] for g in rt(request).world.conflicts()]

    @app.post("/hydra/v1/world/beliefs/{belief_id}/confirm", dependencies=admin_secured)
    async def confirm_belief(belief_id: str, request: Request, correct: bool = True, by: str = "human"):
        w = rt(request).world
        if belief_id not in w.beliefs:
            raise HTTPException(404, "unknown belief")
        w.apply(w.confirm(belief_id, by, correct))
        return w.beliefs[belief_id].model_dump()

    @app.post("/hydra/v1/world/codegraph", dependencies=secured)
    async def codegraph(request: Request, path: str, name: str | None = None):
        from hydra.world.knowledge import code_graph_delta

        try:
            p = confine(rt(request).settings.repositories_root, path)
        except PathNotAllowed as exc:
            raise HTTPException(403, str(exc)) from exc
        if not p.is_dir():
            raise HTTPException(400, "not a directory")
        w = rt(request).world
        d = code_graph_delta(p, w, name)
        return {"version": w.apply(d), "entities": len(d.entities_created), "relations": len(d.relations_added)}

    @app.get("/hydra/v1/world/graph", dependencies=secured)
    async def world_graph(request: Request, limit: int = 300):
        w = rt(request).world
        ents = list(w.entities.values())[-limit:]
        ids = {e.id for e in ents}
        return {"nodes": [{"id": e.id, "label": e.canonical_name or e.id, "type": e.entity_type} for e in ents],
                "edges": [{"source": r.subject_id, "target": r.object_id, "label": r.predicate}
                          for r in w.current_relations() if r.subject_id in ids and r.object_id in ids][:limit * 2],
                "version": w.version}

    # ================================================================== corpus / datasets
    @app.get("/hydra/v1/corpus/stats", dependencies=secured)
    async def corpus_stats(request: Request):
        from hydra.corpus.analytics import CorpusAnalytics

        return CorpusAnalytics(rt(request).corpus).health()

    @app.post("/hydra/v1/corpus/query", dependencies=secured)
    async def corpus_query(body: CorpusQueryBody, request: Request):
        recs = rt(request).corpus.search(text=body.text, record_type=body.record_type, domain=body.domain,
                                         language=body.language, capability=body.capability,
                                         min_quality=body.min_quality,
                                         statuses=set(body.statuses) if body.statuses else None, limit=body.limit)
        return [r.model_dump(mode="json") for r in recs]

    @app.post("/hydra/v1/corpus/ingest", dependencies=secured)
    async def corpus_ingest(record: dict, request: Request):
        from hydra.corpus.records import CorpusRecord

        rec, dec = rt(request).corpus.ingest(CorpusRecord.model_validate(record))
        return {"id": rec.id, "status": rec.training_status.value, "reasons": dec.reasons if dec else []}

    @app.get("/hydra/v1/corpus/records/{record_id}", dependencies=secured)
    async def corpus_record(record_id: str, request: Request):
        r = rt(request).corpus.get(record_id)
        if r is None:
            raise HTTPException(404, "unknown record")
        return r.model_dump(mode="json")

    @app.post("/hydra/v1/corpus/records/{record_id}/review", dependencies=admin_secured)
    async def corpus_review(record_id: str, body: ReviewBody, request: Request):
        return rt(request).corpus.review(record_id, body.approve, body.reviewer, body.training_allowed).model_dump(
            mode="json")

    @app.post("/hydra/v1/corpus/records/{record_id}/tombstone", dependencies=admin_secured)
    async def corpus_tombstone(record_id: str, body: ReasonBody, request: Request):
        return rt(request).corpus.tombstone(record_id, body.reason).model_dump()

    @app.get("/hydra/v1/corpus/lineage/{node_id:path}", dependencies=secured)
    async def corpus_lineage(node_id: str, request: Request):
        c = rt(request).corpus
        return {"ancestors": [e.model_dump() for e in c.ancestors(node_id)],
                "descendants": [e.model_dump() for e in c.descendants(node_id)]}

    @app.post("/hydra/v1/datasets/build", dependencies=admin_secured)
    async def dataset_build(spec: dict, request: Request):
        from hydra.corpus.factory import DatasetSpec

        try:
            return rt(request).datasets.build(DatasetSpec.model_validate(spec)).model_dump(mode="json")
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/hydra/v1/datasets", dependencies=secured)
    async def datasets(request: Request):
        return [r.model_dump(mode="json") for r in rt(request).datasets.releases()]

    # ================================================================== ledger / IP / licenses / releases
    @app.get("/hydra/v1/ledger/verify", dependencies=secured)
    async def ledger_verify(request: Request):
        return rt(request).ledger.verify().model_dump()

    @app.get("/hydra/v1/capture/outbox", dependencies=secured)
    async def capture_outbox(request: Request, limit: int = 100):
        """Capture writes (ledger/corpus) waiting for retry, and those that exhausted their retries."""
        outbox = rt(request).capture_outbox
        if outbox is None:
            return {"pending": 0, "dead_letters": 0, "messages": []}
        return {**outbox.stats(), "messages": outbox.dead_letters(limit)}

    @app.get("/hydra/v1/ledger/events", dependencies=secured)
    async def ledger_events(request: Request, object_type: str | None = None, object_id: str | None = None,
                            event_type: str | None = None, limit: int = 200):
        lg = rt(request).ledger
        evs = lg.for_object(object_type, object_id) if object_type and object_id else list(lg.events(event_type))
        return [e.model_dump() for e in evs[-limit:]]

    @app.post("/hydra/v1/ip/inventions", dependencies=admin_secured)
    async def propose_invention(body: InventionBody, request: Request):
        return rt(request).ip.propose(body.title, problem=body.problem, solution=body.solution,
                                      mechanism=body.mechanism, previous_approach=body.previous_approach,
                                      features=body.features, contributors=body.contributors,
                                      family=body.family).model_dump(mode="json")

    @app.get("/hydra/v1/ip/inventions", dependencies=secured)
    async def inventions(request: Request):
        ip = rt(request).ip
        return {"portfolio": ip.portfolio(), "inventions": [i.model_dump(mode="json") for i in ip.inventions.values()],
                "overlaps": ip.overlaps()}

    @app.post("/hydra/v1/ip/inventions/{inv}/status", dependencies=admin_secured)
    async def invention_status(inv: str, body: StatusBody, request: Request):
        from hydra.ledger.ip import InventionStatus

        return rt(request).ip.set_status(inv, InventionStatus(body.status), body.actor, body.reason).model_dump(mode="json")

    @app.post("/hydra/v1/ip/inventions/{inv}/effects", dependencies=admin_secured)
    async def invention_effect(inv: str, body: EffectBody, request: Request):
        from hydra.ledger.ip import TechnicalEffect

        return rt(request).ip.add_effect(TechnicalEffect(invention_id=inv, **body.model_dump())).model_dump()

    @app.get("/hydra/v1/ip/inventions/{inv}/timeline", dependencies=secured)
    async def invention_timeline(inv: str, request: Request):
        return rt(request).ip.timeline(inv)

    @app.post("/hydra/v1/ip/inventions/{inv}/bundle", dependencies=admin_secured)
    async def invention_bundle(inv: str, request: Request):
        from hydra.ledger.ip import export_bundle

        runtime = rt(request)
        try:
            safe_id(inv, "invention id")
        except PathNotAllowed as exc:
            raise HTTPException(400, str(exc)) from exc
        path = export_bundle(runtime.ip, inv, runtime.settings.data_dir / "ip" / "bundles", runtime.signer)
        return {"path": str(path), "files": sorted(p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file())}

    @app.post("/hydra/v1/licenses/evaluate", dependencies=secured)
    async def license_eval(body: LicenseEvalBody, request: Request):
        from hydra.ledger.licenses import LicenseRecord

        comps = [LicenseRecord(**c) if isinstance(c, dict) else c for c in body.components]
        return rt(request).licenses.evaluate(body.target, comps).model_dump()

    @app.get("/hydra/v1/bom", dependencies=secured)
    async def bom(request: Request, fmt: str = "cyclonedx"):
        from hydra.ledger.bom import cyclonedx, data_bom_from_release, sbom
        from hydra.ledger.licenses import installed_package_licenses

        if fmt == "sbom":
            return sbom()
        runtime = rt(request)
        return cyclonedx(datasets=[data_bom_from_release(r) for r in runtime.datasets.releases()],
                         packages=installed_package_licenses())

    @app.post("/hydra/v1/releases/build", dependencies=admin_secured)
    async def release_build(body: ReleaseBody, request: Request):
        from hydra.ledger.release import ReleaseBuilder, verify_release

        runtime = rt(request)
        path = ReleaseBuilder(runtime.settings.data_dir / "releases", runtime.signer, runtime.ledger).build(
            body.name, components=body.components, eval_results=body.eval_results,
            datasets=[r.model_dump(mode="json") for r in runtime.datasets.releases()][-5:])
        return verify_release(path)

    @app.get("/hydra/v1/releases/{name}/verify", dependencies=secured)
    async def release_verify(name: str, request: Request):
        from hydra.ledger.release import verify_release

        p = rt(request).settings.data_dir / "releases" / name
        if not p.is_dir():
            raise HTTPException(404, "unknown release")
        return verify_release(p)

    @app.post("/hydra/v1/releases/gate", dependencies=secured)
    async def release_gate(body: GateBody, request: Request):
        from hydra.ledger.release import ReleaseArtifact, ReleaseGate

        runtime = rt(request)
        return ReleaseGate(runtime.ip, runtime.licenses, runtime.ledger).evaluate(
            ReleaseArtifact(**body.artifact), body.target).model_dump()

    # ================================================================== models
    @app.post("/hydra/v1/models/resolve", dependencies=secured)
    async def models_resolve(body: ResolveBody, request: Request):
        runtime = rt(request)
        c = body.constraints
        providers = runtime.market.resolve(body.capability, local_only=bool(c.get("local_only")),
                                           min_quality=float(c.get("min_quality", 0)),
                                           max_latency_ms=c.get("max_latency_ms"))
        from hydra.training.autoquant import ModelCapabilityGraph

        graph = ModelCapabilityGraph.from_runtime(runtime.registry, runtime.factory).query(
            body.capability.split(".")[0], local=bool(c.get("local_only")), max_memory_gb=c.get("max_memory_gb"),
            min_quality=float(c.get("min_quality", 0)))
        rc = {"quality": c.get("min_quality"), "max_memory_gb": c.get("max_memory_gb"),
              "local": c.get("local_only")}
        variant = runtime.factory.resolve(body.capability, {k: v for k, v in rc.items() if v is not None})             if runtime.factory else None
        return {"providers": [p.model_dump() for p in providers[:10]], "graph": graph[:10],
                "factory_variant": variant.model_dump(mode="json") if variant else None}

    @app.get("/hydra/v1/models/graph", dependencies=secured)
    async def models_graph(request: Request):
        from hydra.training.autoquant import ModelCapabilityGraph

        runtime = rt(request)
        g = ModelCapabilityGraph.from_runtime(runtime.registry, runtime.factory)
        return {k: v.model_dump() for k, v in g.nodes.items()}

    @app.post("/hydra/v1/models/{model_id:path}/discover", dependencies=secured)
    async def model_discover(model_id: str, request: Request, apply: bool = False):
        from hydra.discovery import CapabilityDiscovery

        runtime = rt(request)
        if model_id not in runtime.registry.models:
            raise HTTPException(404, "unknown model")

        async def work():
            cd = CapabilityDiscovery(runtime.evaluator, runtime.settings.data_dir / "discovery")
            prof = await cd.discover(runtime.registry.get(model_id))
            applied = CapabilityDiscovery.apply(prof, runtime.registry) if apply else {}
            return {"profile": prof.model_dump(mode="json"), "applied": applied}
        return _spawn("discover", work())

    @app.post("/hydra/v1/models/{model_id:path}/lifecycle", dependencies=admin_secured)
    async def model_lifecycle(model_id: str, body: LifecycleBody, request: Request):
        from hydra.discovery import ModelLifecycle

        runtime = rt(request)
        lc = ModelLifecycle(runtime.settings.data_dir / "model_lifecycle.json", docs=runtime.documents)
        st = lc.transition(model_id, body.to, body.reason, body.actor)
        if model_id in runtime.registry.models and body.to in ("RETIRED", "ARCHIVED", "DEPRECATED"):
            runtime.registry.get(model_id).enabled = body.to == "DEPRECATED"
        return st

    # ================================================================== cluster / fabric
    @app.post("/v1/cluster/heartbeat", dependencies=admin_secured)
    async def heartbeat(node: dict, request: Request):
        from hydra.cluster.nodes import HardwareNode

        n = rt(request).nodes.heartbeat(HardwareNode.model_validate(node))
        return {"ok": True, "node": n.id}

    @app.get("/v1/cluster/nodes", dependencies=secured)
    async def cluster_nodes(request: Request):
        nodes = rt(request).nodes
        return {"summary": nodes.summary(), "nodes": [n.model_dump() for n in nodes.nodes.values()]}

    @app.post("/v1/cluster/place", dependencies=secured)
    async def cluster_place(body: PlaceBody, request: Request):
        from hydra.cluster.scheduler import SLA_CLASSES, estimate_work
        from hydra.core.contracts import TaskType

        runtime = rt(request)
        tt = TaskType(body.task_type)
        models = [m for m in runtime.registry.available()]
        work = estimate_work(body.prompt_chars, body.expected_output_tokens)
        pl = runtime.scheduler.place(models, quality_of=lambda m: m.quality(tt), mode=body.mode, private=body.private,
                                     conversation=body.conversation_id, work=work, sla=SLA_CLASSES.get(body.sla))
        return {"work": work.model_dump(), "placements": [p.model_dump() for p in pl[:10]]}

    @app.get("/v1/fabric/stats", dependencies=secured)
    async def fabric_stats(request: Request):
        return rt(request).queue.stats()

    @app.post("/v1/fabric/work", dependencies=secured, status_code=202)
    async def fabric_submit(body: WorkBody, request: Request):
        from hydra.cluster.fabric import Priority, WorkItem

        w = rt(request).queue.submit(WorkItem(capability=body.capability, payload=body.payload,
                                              priority=Priority.parse(body.priority),
                                              idempotency_key=body.idempotency_key, timeout_ms=body.timeout_ms))
        return w.model_dump()

    @app.get("/v1/fabric/work/{item_id}", dependencies=secured)
    async def fabric_get(item_id: str, request: Request):
        w = rt(request).queue.get(item_id)
        if w is None:
            raise HTTPException(404, "unknown work item")
        return w.model_dump()

    # ================================================================== training / specialists
    @app.get("/hydra/v1/training/runs", dependencies=secured)
    async def training_runs(request: Request):
        from hydra.training.lab import TrainingOrchestrator

        return [r.model_dump(mode="json") for r in TrainingOrchestrator(rt(request)).runs.values()]

    @app.post("/hydra/v1/training/runs", dependencies=admin_secured, status_code=202)
    async def training_start(body: TrainingBody, request: Request):
        from hydra.corpus.factory import DatasetSpec
        from hydra.training.lab import TrainingOrchestrator, TrainingRecipe

        runtime = rt(request)
        recipe = TrainingRecipe.model_validate(body.recipe)
        spec = DatasetSpec.model_validate(body.dataset) if body.dataset else None
        return _spawn("train", TrainingOrchestrator(runtime).run(recipe, spec))

    @app.get("/hydra/v1/training/specialists", dependencies=secured)
    async def specialists(request: Request, window_days: float = 30, min_volume_month: float = 1000):
        from hydra.training.lab import SpecialistDiscovery, traces_from_tasks

        runtime = rt(request)
        traces = traces_from_tasks(await runtime.telemetry.recent_tasks(5000), runtime.settings.data_dir / "flight")
        sd = SpecialistDiscovery()
        cl = sd.clusters(traces)
        return {"clusters": [c.model_dump() for c in cl],
                "proposals": [p.model_dump() for p in sd.propose(cl, window_days=window_days,
                                                                 min_volume_month=min_volume_month)]}

    @app.get("/hydra/v1/training/dashboard", dependencies=secured)
    async def training_dashboard(request: Request):
        from hydra.training.lab import meta_learning_dashboard

        runtime = rt(request)
        return meta_learning_dashboard(await runtime.telemetry.recent_runs(), runtime.registry)

    @app.post("/hydra/v1/federated/analytics", dependencies=secured)
    async def federated_analytics(body: FederatedCountBody):
        from hydra.federated import PrivacyConfig, federated_count

        return federated_count(body.local_counts, PrivacyConfig(min_count=body.min_count,
                                                                differential_privacy=body.differential_privacy))

    @app.get("/hydra/v1/lab/improvements", dependencies=secured)
    async def improvements(request: Request):
        from hydra.replay import ImprovementLab

        return [p.model_dump() for p in await ImprovementLab(rt(request)).analyze()]

    # ================================================================== governance
    @app.get("/hydra/v1/flags", dependencies=secured)
    async def flags(request: Request):
        return rt(request).flags.snapshot()

    @app.post("/hydra/v1/flags/{name}", dependencies=admin_secured)
    async def set_flag(name: str, body: FlagBody, request: Request):
        return rt(request).flags.set(name, body.value, body.description).model_dump()

    @app.get("/hydra/v1/config/{env}", dependencies=secured)
    async def config_get(env: str, request: Request):
        try:
            c = rt(request).configs.current(env)
        except PathNotAllowed as exc:
            raise HTTPException(400, str(exc)) from exc
        return c.model_dump() if c else {}

    @app.post("/hydra/v1/config/{env}", dependencies=admin_secured)
    async def config_commit(env: str, body: ConfigBody, request: Request):
        try:
            return rt(request).configs.commit(env, body.values, body.author, body.message).model_dump()
        except PathNotAllowed as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/hydra/v1/policy/rules", dependencies=secured)
    async def policy_rules(request: Request):
        e = rt(request).policy_dsl
        return {"version": e.version, "default": e.default, "rules": [r.model_dump() for r in e.rules]}

    @app.post("/hydra/v1/policy/evaluate", dependencies=secured)
    async def policy_evaluate(body: PolicyEvalBody, request: Request):
        return rt(request).policy_dsl.evaluate(body.facts).model_dump()

    @app.get("/hydra/v1/secrets", dependencies=secured)
    async def secrets(request: Request):
        return {"refs": rt(request).secrets.refs()}  # references only, never values

    @app.post("/hydra/v1/redteam/run", dependencies=admin_secured)
    async def redteam(request: Request):
        from hydra.governance.redteam import RedTeam

        return [r.model_dump() for r in await RedTeam(rt(request)).run()]

    @app.get("/hydra/v1/system/invariants", dependencies=secured)
    async def invariants(request: Request):
        from hydra.governance.invariants import check_invariants

        return [c.model_dump() for c in await check_invariants(rt(request))]

    @app.get("/hydra/v1/system/dod", dependencies=secured)
    async def dod(request: Request, recovery: bool = False):
        from hydra.governance.invariants import definition_of_done, summary

        rows = await definition_of_done(rt(request), run_recovery=recovery)
        return {"summary": summary(rows), "rows": [r.model_dump() for r in rows]}

    @app.post("/hydra/v1/evals/e2e", dependencies=secured, status_code=202)
    async def e2e(request: Request, limit: int | None = None):
        from hydra.evals.e2e import run_e2e

        return _spawn("e2e", run_e2e(rt(request), limit=limit))

    # ================================================================== replay / observability
    @app.get("/hydra/v1/tasks/{task_id}/flight", dependencies=secured)
    async def flight(task_id: UUID, request: Request):
        p = rt(request).settings.data_dir / "flight" / f"{task_id}.json"
        if not p.exists():
            raise HTTPException(404, "no flight record")
        return json.loads(p.read_text(encoding="utf-8"))

    @app.post("/hydra/v1/tasks/{task_id}/replay", dependencies=secured)
    async def task_replay(task_id: UUID, body: ReplayBody, request: Request):
        from hydra.replay import ReplayEngine

        eng = ReplayEngine(rt(request))
        if body.mode == "audit":
            return (await eng.audit(str(task_id))).model_dump()
        return (await eng.rerun(str(task_id), replace_models=body.replace_models or None,
                                config=body.config or None)).model_dump()

    @app.get("/hydra/v1/tasks/{task_id}/flamegraph", dependencies=secured)
    async def flamegraph(task_id: UUID, request: Request):
        fg = rt(request).tracer.flamegraph(str(task_id))
        if fg is None:
            raise HTTPException(404, "no trace")
        return fg

    @app.get("/hydra/v1/observability", dependencies=secured)
    async def observability(request: Request):
        t = rt(request).tracer
        return {"stage_profile_ms": t.stage_profile(), "cost_attribution": t.cost_attribution()}

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics(request: Request):
        runtime = rt(request)
        nodes = runtime.nodes.summary()
        gauges = {"hydra_cluster_nodes_healthy": nodes["healthy"], "hydra_cluster_free_vram_gb": nodes["free_vram_gb"],
                  "hydra_world_version": runtime.world.version, "hydra_corpus_records": len(runtime.corpus.records),
                  "hydra_ledger_events": len(runtime.ledger),
                  "hydra_models_enabled": sum(1 for m in runtime.registry.all() if m.enabled)}
        if runtime.capture_outbox is not None:
            stats = runtime.capture_outbox.stats()
            gauges["hydra_capture_outbox_pending"] = stats["pending"]
            gauges["hydra_capture_outbox_dead_letters"] = stats["dead_letters"]
        if runtime.settings.runtime_api:  # HYDRA-SO runtime line (transactional outbox)
            from hydra.api import native as runtime_api
            from hydra.core.outbox_metrics import collect_outbox_metrics

            line = collect_outbox_metrics(runtime_api.capture_uow.outbox)
            gauges["hydra_runtime_outbox_pending"] = line.pending
            gauges["hydra_runtime_outbox_dead_letters"] = line.dead_letters
            gauges["hydra_runtime_outbox_oldest_pending_age_seconds"] = line.oldest_pending_age_seconds or 0
        return runtime.tracer.prometheus(gauges)

    # ================================================================== edge / translation
    @app.post("/v1/translate", dependencies=secured)
    async def translate(body: TranslateBody, request: Request):
        from hydra.edge.translation import TranslationEngine, TranslationRequest

        runtime = rt(request)
        eng = getattr(runtime, "_translator", None) or TranslationEngine(runtime)
        runtime._translator = eng
        try:
            return (await eng.translate(TranslationRequest(**body.model_dump()))).model_dump()
        except BudgetExceeded as exc:
            raise HTTPException(413, str(exc)) from exc

    @app.get("/v1/glossaries/{name}", dependencies=secured)
    async def glossary_get(name: str, request: Request):
        from hydra.edge.translation import GlossaryStore

        return GlossaryStore(rt(request).settings.data_dir / "glossaries.json", docs=rt(request).documents).get(name)

    @app.put("/v1/glossaries/{name}", dependencies=secured)
    @app.post("/v1/glossaries/{name}", dependencies=secured)  # one route per method: unique operation ids
    async def glossary_put(name: str, body: GlossaryBody, request: Request):
        from hydra.edge.translation import GlossaryStore

        runtime = rt(request)
        store = GlossaryStore(runtime.settings.data_dir / "glossaries.json", docs=runtime.documents)
        res = store.put(name, body.terms)
        if getattr(runtime, "_translator", None) is not None:
            runtime._translator.glossaries = store
        return res

    @app.get("/hydra/v1/edge/profile", dependencies=secured)
    async def edge_profile():
        from hydra.edge.profiles import detect_profile, llamacpp_cmake_args

        p = detect_profile()
        return {**p.as_dict(), "llamacpp_cmake_args": llamacpp_cmake_args(p)}

    @app.get("/hydra/v1/edge/scout", dependencies=secured)
    async def edge_scout(request: Request):
        from hydra.edge.profiles import detect_profile
        from hydra.edge.scout import best_fit, scan_gguf, scan_ollama

        runtime = rt(request)
        p = detect_profile()
        found = await asyncio.to_thread(scan_ollama, runtime.settings.ollama_base_url, p)
        found += await asyncio.to_thread(scan_gguf, [runtime.settings.data_dir / "factory",
                                                     Path("models")], p)
        return {"profile": p.profile, "models": [m.model_dump() for m in found], "recommendation": best_fit(found)}

    @app.post("/hydra/v1/edge/autobuild", dependencies=admin_secured, status_code=202)
    async def edge_autobuild(body: AutobuildBody, request: Request):
        from hydra.edge.autobuild import apply_manifest, autobuild, save_manifest

        runtime = rt(request)

        async def work():
            m = await autobuild(model=body.model, runtime=body.runtime, ollama_url=runtime.settings.ollama_base_url,
                                llama_server=runtime.settings.llama_server or None, signer=runtime.signer)
            save_manifest(m, runtime.settings.data_dir / "runtime" / "runtime-manifest.json")
            applied = apply_manifest(m, registry=runtime.registry) if body.apply and m.selected else {}
            return {"manifest": m.model_dump(), "applied": applied}
        return _spawn("autobuild", work())

    @app.post("/hydra/v1/edge/residency/{model_id:path}", dependencies=secured)
    async def edge_residency(model_id: str, request: Request):
        from hydra.edge.scout import ResidencyManager

        runtime = rt(request)
        rm = ResidencyManager(runtime.registry, runtime.settings.ollama_base_url)
        return (await rm.ensure(model_id)).model_dump()

    @app.post("/hydra/v1/edge/sync/export", dependencies=admin_secured)
    async def sync_export(request: Request, world_version: int = 0, corpus_offset: int = 0, origin: str = ""):
        from hydra.edge.sync import SyncCursor, export_delta

        runtime = rt(request)
        b = export_delta(runtime, SyncCursor(world_version=world_version, corpus_offset=corpus_offset),
                         origin or runtime.settings.node_id or "edge")
        return b.model_dump()

    @app.post("/hydra/v1/edge/sync/import", dependencies=admin_secured)
    async def sync_import(body: SyncImportBody, request: Request):
        from hydra.edge.sync import SyncBundle, import_delta, trusted_sync_keys

        runtime = rt(request)
        return import_delta(runtime, SyncBundle.model_validate(body.bundle), trusted_sync_keys(runtime)).model_dump()

    # ================================================================== studio
    @app.get("/studio", response_class=HTMLResponse)
    async def studio():
        return HTMLResponse((Path(__file__).parent / "studio.html").read_text(encoding="utf-8"), headers=STUDIO_HEADERS)
