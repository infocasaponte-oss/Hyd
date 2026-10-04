# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Optional Hyd-only service for clients that previously used a decision sidecar."""
from __future__ import annotations

import argparse
from types import SimpleNamespace

from fastapi import Depends, FastAPI, Header, Request

from hydra.api.security import authenticate
from hydra.core.config import Settings
from hydra.governance.rate_limit import SlidingWindowRateLimiter
from hydra.hyd.api import register
from hydra.hyd.controller import HydController


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    hyd = HydController(settings.hyd_model_path, settings.hyd_calibration_path, settings.hyd_authority_evidence_path)
    app = FastAPI(title="Hyd native decisions")
    app.state.runtime = SimpleNamespace(kernel=SimpleNamespace(router=SimpleNamespace(observer=hyd)))
    limiter = SlidingWindowRateLimiter()

    async def secured(request: Request, authorization: str | None = Header(default=None),
                      x_api_key: str | None = Header(default=None), x_hydra_token: str | None = Header(default=None)):
        from hydra.api.client_keys import client_route, lookup
        token = x_api_key or x_hydra_token or (authorization or "").removeprefix("Bearer ").strip()
        identity = authenticate(settings, request.client.host if request.client else "", token)
        client_route(identity, request.method, request.url.path)
        limit = settings.api_rate_limit_per_minute
        if identity.startswith("client:"):
            limit = min(limit, int(lookup(settings.client_keys_file, token)["requests_per_minute"]))
        limiter.check(identity, limit, 60)

    dependencies = [Depends(secured)]
    register(app, dependencies)

    @app.get("/v1/models", dependencies=dependencies)
    async def models():
        return {"models": [{"name": hyd.model, "run": hyd.engine.ranker.revision,
                            "description": "HYDRA-owned CPU candidate ranker; routing baseline",
                            "backend": "hyd-native-cpu", "temperature": hyd.engine.ranker.temperature}]}

    return app


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8009)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port)
