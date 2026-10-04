# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Authenticated, read-only public-web tools for Studio and local integrations."""
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from hydra.tools.capabilities import RESEARCHER
from hydra.tools.definitions import ToolCall, ToolContext


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    engine: Literal["brave", "google", "bing", "duckduckgo"] = "brave"
    limit: int = Field(default=5, ge=1, le=10)
    private: bool = False


class ReadBody(BaseModel):
    url: str = Field(min_length=1, max_length=4000)
    private: bool = False


def register_web_routes(app, runtime, dependencies):
    async def execute(name, body, request):
        rt = runtime(request)
        if rt.settings.offline or not rt.settings.public_web_enabled or body.private:
            raise HTTPException(403, "Web access is disabled in offline/private mode")
        ctx = ToolContext(task_id=uuid4(), capabilities=RESEARCHER.model_copy(deep=True))
        result = await rt.kernel.coder.executor.execute(ToolCall(name=name, arguments=body.model_dump(exclude={"private"}),
                                                                requested_by="studio-web"), ctx)
        if not result.success:
            raise HTTPException(502, result.error or "Web tool failed")
        return result.output

    @app.post("/hydra/v1/web/search", dependencies=dependencies)
    async def search(body: SearchBody, request: Request):
        return await execute("web.search", body, request)

    @app.post("/hydra/v1/web/read", dependencies=dependencies)
    async def read(body: ReadBody, request: Request):
        return await execute("web.read", body, request)
