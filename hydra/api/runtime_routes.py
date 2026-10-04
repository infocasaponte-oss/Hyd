# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Mount the native compatibility API (``hydra.api.native``) into the unified gateway.

Platform routes win on (path, method) collisions:

* ``GET /health``            platform health (``hydra: ok`` kept for runtime clients)
* ``GET /v1/models``         platform model list; the runtime GGUF scan moves to
                             ``GET /hydra/v1/models/artifacts``
* ``POST /v1/translate``     platform engine (accepts the runtime schema)
* ``PUT /v1/glossaries/{}``  platform glossary store

Everything else (``/ready``, ``/v1/chat``, ``/hydra/v1/tasks/route|execute``,
``/hydra/v1/admin/*``, ``/hydra/v1/coding/verify-fix``) is served by the runtime line with
its own token policy (``HYDRA_API_TOKEN`` / ``HYDRA_ADMIN_TOKEN``) and its transactional
outbox worker, which runs inside the gateway lifespan.

The runtime line keeps process-wide state under ``./runtime`` (HYDRA-SO layout), so it is
mounted once per process even when several apps are created (tests).
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager, nullcontext, suppress
from dataclasses import replace
from types import ModuleType

from fastapi import FastAPI
from fastapi.routing import APIRoute

from hydra.ledger.runtime_anchor import anchor_runtime_chains

log = logging.getLogger("hydra.api")

RELOCATED = {("/v1/models", "GET"): "/hydra/v1/models/artifacts"}
_PARAM = re.compile(r"\{[^}]+\}")


def _shape(path: str) -> str:
    """``/v1/glossaries/{name}`` and ``/v1/glossaries/{glossary_id}`` are the same route."""
    return _PARAM.sub("{}", path)


def runtime_module() -> ModuleType:
    from hydra.api import native as api

    return api


def register_runtime_routes(app: FastAPI) -> list[str]:
    """Append runtime routes that do not collide with platform routes. Returns what was mounted."""
    runtime = runtime_module()
    taken = {(_shape(route.path), method) for route in app.routes if isinstance(route, APIRoute)
             for method in route.methods}
    mounted = []
    for route in runtime.app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods):
            path = RELOCATED.get((route.path, method), route.path)
            if (_shape(path), method) in taken:
                continue
            app.add_api_route(path, route.endpoint, methods=[method], name=f"runtime.{route.name}",
                              response_model=route.response_model, status_code=route.status_code,
                              tags=["runtime"], summary=route.summary, description=route.description)
            taken.add((_shape(path), method))
            mounted.append(f"{method} {path}")
    return mounted


def anchor_now(ledger) -> dict | None:
    """Record the runtime event/provenance chain heads in the signed platform ledger."""
    runtime = runtime_module()
    return anchor_runtime_chains(ledger, runtime.kernel.events, runtime.provenance)


@asynccontextmanager
async def runtime_lifespan(enabled: bool, api_key: str = "", ledger=None, anchor_interval_s: float = 300.0,
                           world=None, admin_token: str = "", client_keys_file=None):
    """Outbox recovery + worker of the runtime line, bound to the gateway lifespan.

    Gateway and admin tokens given in code (not only through HYDRA_API_KEY/HYDRA_API_TOKEN and
    HYDRA_ADMIN_TOKEN) also protect the runtime routes while this app is running. With a ledger, the runtime
    evidence chains are anchored in it periodically and on shutdown; with a world model,
    runtime beliefs (verified patches) are recorded in it."""
    if not enabled:
        yield
        return
    runtime = runtime_module()
    previous = runtime.security_config
    previous_beliefs = runtime.learning.beliefs
    overrides = {k: v for k, v in (("api_token", api_key), ("admin_token", admin_token),
                                   ("client_keys_file", str(client_keys_file) if client_keys_file else "")) if v}
    if overrides:
        runtime.security_config = replace(previous, **overrides)
    if world is not None:
        from hydra.world.runtime_beliefs import WorldBeliefStore

        runtime.learning.beliefs = WorldBeliefStore(world, previous_beliefs.path, log=previous_beliefs.log)
    worker = getattr(runtime.app.state, "outbox_worker_task", None)
    running = worker is not None and not worker.done()  # already started by another app in this process

    async def anchor_loop() -> None:
        while True:
            await asyncio.sleep(anchor_interval_s)
            try:
                await asyncio.to_thread(anchor_now, ledger)
            except Exception:
                log.exception("runtime chain anchoring failed")

    anchoring = asyncio.create_task(anchor_loop()) if ledger is not None and anchor_interval_s > 0 else None
    try:
        async with nullcontext() if running else runtime.lifespan(runtime.app):
            yield
    finally:
        runtime.security_config = previous
        runtime.learning.beliefs = previous_beliefs
        if anchoring is not None:
            anchoring.cancel()
            with suppress(asyncio.CancelledError):
                await anchoring
        if ledger is not None:
            try:
                anchor_now(ledger)
            except Exception:
                log.exception("runtime chain anchoring failed")
