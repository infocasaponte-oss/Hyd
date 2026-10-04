# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""HYDRA gateway. Runtimes (vLLM, Ollama, llama.cpp) must never be exposed directly:
only this gateway talks to them."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import hydra
from hydra.api.evaluation_routes import register as register_evaluation_routes
from hydra.api.os_routes import register_os_routes
from hydra.api.platform_routes import register_platform_routes
from hydra.api.runtime_routes import register_runtime_routes, runtime_lifespan
from hydra.api.security import authenticate, authorize_admin
from hydra.api.web_routes import register_web_routes
from hydra.blackboard.projector import replay
from hydra.core.bootstrap import HydraRuntime, build_runtime
from hydra.core.config import Settings
from hydra.core.contracts import ExecutionMode, HydraRequest, HydraResponse, Message, TaskType
from hydra.core.events import HydraEvent
from hydra.core.kernel import HydraTaskFailed
from hydra.governance.rate_limit import SlidingWindowRateLimiter
from hydra.memory.graph import MemoryGraph
from hydra.memory.models import MemoryStatus, MemoryType


class Feedback(BaseModel):
    score: float = Field(ge=0, le=1)


class ChatBody(BaseModel):
    model: str = "hydra"
    messages: list[Message]
    temperature: float | None = None
    max_tokens: int | None = None


class Listeners:
    """Fan-out of bus events to per-task SSE queues (one bus subscription in total)."""

    def __init__(self) -> None:
        self.queues: dict[UUID, asyncio.Queue] = {}

    async def __call__(self, event: HydraEvent) -> None:
        if q := self.queues.get(event.task_id):
            q.put_nowait(event)


def create_app(settings: Settings | None = None, **overrides: Any) -> FastAPI:
    settings = settings or Settings()
    rate_limiter = SlidingWindowRateLimiter()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = await build_runtime(settings, **overrides)
        app.state.runtime = runtime
        app.state.listeners = Listeners()
        await runtime.bus.subscribe(None, app.state.listeners)
        async with runtime_lifespan(settings.runtime_api, settings.api_key, ledger=runtime.ledger,
                                    admin_token=settings.admin_token, client_keys_file=settings.client_keys_file,
                                    anchor_interval_s=settings.runtime_anchor_interval_s, world=runtime.world):
            yield
        await runtime.close()

    app = FastAPI(
        title="HYDRA Cognitive Engine",
        version=hydra.__version__,
        description=f"{hydra.__copyright__} Proprietary software.",
        lifespan=lifespan,
    )

    app.state.rate_limiter = rate_limiter  # shared with the WebSocket endpoint

    def rt(request: Request) -> HydraRuntime:
        return request.app.state.runtime

    async def auth(request: Request,
                   authorization: str | None = Header(default=None),
                   x_api_key: str | None = Header(default=None),
                   x_hydra_token: str | None = Header(default=None)) -> str:
        token = x_api_key or x_hydra_token or (authorization or "").removeprefix("Bearer ").strip()
        return authenticate(settings, request.client.host if request.client else "", token)

    async def throttle(request: Request, identity: str = Depends(auth)) -> None:
        from hydra.api.client_keys import client_route, lookup
        client_route(identity, request.method, request.url.path)
        limit = settings.api_rate_limit_per_minute
        if identity.startswith('client:'):
            token = request.headers.get('x-api-key') or request.headers.get('x-hydra-token') or request.headers.get('authorization', '').removeprefix('Bearer ').strip()
            client = lookup(settings.client_keys_file, token)
            limit = min(limit, int(client['requests_per_minute']))
        rate_limiter.check(identity, limit, 60.0)

    async def admin(request: Request, x_hydra_admin_token: str | None = Header(default=None)) -> str:
        return authorize_admin(settings, request.client.host if request.client else "", x_hydra_admin_token)

    secured = [Depends(throttle)]
    admin_secured = [Depends(throttle), Depends(admin)]
    from hydra.hyd.api import register as register_hyd_routes
    register_hyd_routes(app, secured)

    # ---------------------------------------------------------------- health
    @app.get("/health")
    async def health(request: Request) -> dict:
        runtime = rt(request)
        checks = {}
        for name, provider in runtime.providers.items():
            if any(m.provider == name and m.enabled for m in runtime.registry.all()):
                with contextlib.suppress(Exception):
                    checks[name] = await asyncio.wait_for(provider.health(), 5)
                checks.setdefault(name, False)
        return {"status": "ok", "hydra": "ok", "version": hydra.__version__, "offline": runtime.settings.offline,
                "runtimes": checks}

    # ---------------------------------------------------------------- core
    @app.post("/v1/hydra", response_model=HydraResponse, dependencies=secured)
    async def run_hydra(body: HydraRequest, request: Request):
        try:
            return await rt(request).lab.serve(body, task_id=uuid4())  # canary split + shadow copies
        except HydraTaskFailed as exc:
            code = 503 if exc.kind in ("unavailable", "rate_limit", "timeout") else 502
            return JSONResponse(status_code=code, content={
                "error": exc.public_message(), "kind": exc.kind, "task_id": str(exc.task_id)})

    @app.post("/v1/hydra/stream", dependencies=secured)
    async def stream_hydra(body: HydraRequest, request: Request):
        runtime = rt(request)
        listeners: Listeners = request.app.state.listeners
        task_id = uuid4()
        queue: asyncio.Queue = asyncio.Queue()
        listeners.queues[task_id] = queue

        async def run():
            try:
                return await runtime.lab.serve(body, task_id=task_id)
            except HydraTaskFailed as exc:
                return exc

        async def events():
            job = asyncio.create_task(run())
            try:
                while True:
                    get = asyncio.create_task(queue.get())
                    done, _ = await asyncio.wait({get, job}, return_when=asyncio.FIRST_COMPLETED)
                    if get in done:
                        ev: HydraEvent = get.result()
                        yield f"event: {ev.type.value}\ndata: {ev.model_dump_json()}\n\n"
                        continue
                    get.cancel()
                    while not queue.empty():
                        ev = queue.get_nowait()
                        yield f"event: {ev.type.value}\ndata: {ev.model_dump_json()}\n\n"
                    result = job.result()
                    if isinstance(result, HydraTaskFailed):
                        yield f"event: error\ndata: {json.dumps({'error': result.public_message(), 'kind': result.kind})}\n\n"
                    else:
                        yield f"event: result\ndata: {result.model_dump_json()}\n\n"
                    break
            finally:
                listeners.queues.pop(task_id, None)
                if not job.done():
                    job.cancel()

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"X-Hydra-Task-Id": str(task_id), "Cache-Control": "no-cache"})

    # ---------------------------------------------------------------- tasks
    async def _history(runtime: HydraRuntime, task_id: UUID) -> list[HydraEvent]:
        if runtime.event_sink is not None:
            return await runtime.event_sink.history(task_id)
        return await runtime.bus.history(task_id)

    @app.get("/v1/tasks/{task_id}", dependencies=secured)
    async def get_task(task_id: UUID, request: Request):
        task = await rt(request).telemetry.get_task(task_id)
        if task is None:
            raise HTTPException(404, "task not found")
        return task

    @app.get("/v1/tasks/{task_id}/events", dependencies=secured)
    async def task_events(task_id: UUID, request: Request):
        events = await _history(rt(request), task_id)
        if not events:
            raise HTTPException(404, "task not found")
        return [e.model_dump(mode="json") for e in events]

    @app.get("/v1/tasks/{task_id}/replay", dependencies=secured)
    async def task_replay(task_id: UUID, request: Request):
        events = await _history(rt(request), task_id)
        if not events:
            raise HTTPException(404, "task not found")
        return replay(events).model_dump(mode="json")

    @app.post("/v1/tasks/{task_id}/feedback", dependencies=secured)
    async def feedback(task_id: UUID, body: Feedback, request: Request):
        runtime = rt(request)
        updated = await runtime.telemetry.feedback(task_id, body.score)
        task = await runtime.telemetry.get_task(task_id)
        if task and task.route and task.final_response:
            task_type = TaskType(task.route["task_type"])
            for model_id in task.final_response["meta"]["models_used"]:
                if model := runtime.registry.models.get(model_id):
                    runtime.registry.record(model_id, task_type, body.score, model.estimated_latency_ms)
        return {"updated_runs": updated}

    # ---------------------------------------------------------------- models & tools
    @app.get("/v1/models", dependencies=secured)
    async def models(request: Request):
        # The public OpenAI-compatible surface exposes HYDRA modes, not physical
        # backends. Physical models (including qwen2.5-coder:7b) remain internal.
        usable = rt(request).registry.available()
        return [
            {
                "id": "hydra" if mode is ExecutionMode.BALANCED else f"hydra-{mode.value}",
                "object": "model",
                "owned_by": "hydra",
                # PRIVATE never leaves the machine, so it needs a usable local backend.
                "available": any(m.local for m in usable) if mode is ExecutionMode.PRIVATE else bool(usable),
            }
            for mode in ExecutionMode
        ]

    @app.get("/hydra/v1/models/catalog", dependencies=secured)
    async def model_catalog(request: Request):
        """Internal backend catalogue (Studio): physical models behind the HYDRA modes."""
        registry = rt(request).registry
        return [{**m.model_dump(), "available": registry.breaker.available(m.id),
                 "provider_healthy": registry.provider_healthy(m.provider),
                 "installed": registry.model_installed(m.id)} for m in registry.all()]

    @app.get("/v1/metrics/models", dependencies=secured)
    async def model_metrics(request: Request):
        return await rt(request).telemetry.model_stats()

    @app.get("/v1/tools", dependencies=secured)
    async def tools(request: Request):
        return [t.definition.model_dump() for t in rt(request).tools.tools.values()]

    # ---------------------------------------------------------------- memory
    @app.get("/v1/memory", dependencies=secured)
    async def list_memory(request: Request, type: MemoryType | None = None, limit: int = 100):
        items = await rt(request).memory.all(type)
        return [i.model_dump(mode="json", exclude={"embedding"}) for i in items[:limit]]

    @app.get("/v1/memory/search", dependencies=secured)
    async def search_memory(q: str, request: Request, limit: int = 10):
        return await rt(request).retriever.search(q, limit)

    @app.post("/v1/memory/{item_id}/canonical", dependencies=secured)
    async def canonical(item_id: str, request: Request):
        store = rt(request).memory
        item = await store.get(item_id)
        if item is None:
            raise HTTPException(404, "memory not found")
        item.status = MemoryStatus.CANONICAL
        await store.save(item)
        return item.model_dump(mode="json", exclude={"embedding"})

    @app.post("/v1/memory/{item_id}/resolve", dependencies=secured)
    async def resolve(item_id: str, request: Request):
        winner = await rt(request).memory_compiler.resolve_conflict(item_id)
        if winner is None:
            raise HTTPException(404, "memory not found")
        return winner.model_dump(mode="json", exclude={"embedding"})

    @app.get("/v1/memory/graph", dependencies=secured)
    async def graph(node: str, request: Request, predicate: str | None = None):
        g = MemoryGraph.build(await rt(request).memory.all(MemoryType.SEMANTIC))
        if predicate:
            return {"node": node, "predicate": predicate, "dependents": g.dependents(node, predicate)}
        return {"node": node, "edges": [{"subject": s, "predicate": p, "object": o} for s, p, o in g.neighbors(node)]}

    # ---------------------------------------------------------------- OpenAI-compatible façade
    @app.post("/v1/chat/completions", dependencies=secured)
    async def chat_completions(body: ChatBody, request: Request):
        suffix = body.model.removeprefix("hydra").strip("-") or "balanced"
        try:
            mode = ExecutionMode(suffix)
        except ValueError:
            raise HTTPException(400, f"unknown model '{body.model}'; use hydra, hydra-fast, hydra-deep, "
                                     "hydra-max or hydra-private") from None
        try:
            result = await rt(request).lab.serve(HydraRequest(messages=body.messages, mode=mode), task_id=uuid4())
        except HydraTaskFailed as exc:
            raise HTTPException(502, exc.public_message()) from exc
        return {
            "id": f"chatcmpl-{result.meta.task_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": result.answer}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "hydra": result.meta.model_dump(mode="json"),
        }

    register_os_routes(app, rt, secured, admin_secured)
    register_platform_routes(app, rt, secured, admin_secured)
    register_web_routes(app, rt, secured)
    register_evaluation_routes(app, secured, settings.evaluation_candidate_version)
    if settings.runtime_api:  # after platform routes: they win on (path, method) collisions
        app.state.runtime_routes = register_runtime_routes(app)
    return app


app = create_app()
