# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""OpenAI-compatible provider: vLLM, llama.cpp server, and cloud APIs."""

from __future__ import annotations

import json
import time

import httpx

from hydra.core.contracts import ModelRequest, ModelResponse
from hydra.core.errors import ErrorKind, ModelError
from hydra.providers.base import ModelProvider, http_error


def to_openai_message(m: dict) -> dict:
    """HYDRA message (content + images) -> OpenAI chat message with content parts."""
    images = m.get("images")
    if not images:
        return {k: v for k, v in m.items() if k != "images"}
    parts = [{"type": "text", "text": m.get("content", "")}]
    parts += [{"type": "image_url", "image_url": {"url": url}} for url in images]
    return {**{k: v for k, v in m.items() if k not in ("images", "content")}, "content": parts}


class OpenAICompatibleProvider(ModelProvider):
    def __init__(self, base_url: str, api_key: str = "", timeout_s: float = 120) -> None:
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=timeout_s,
        )

    async def generate(self, model_id: str, request: ModelRequest) -> ModelResponse:
        body: dict = {
            "model": model_id,
            "messages": [to_openai_message(m) for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if reasoning := request.metadata.get("reasoning"):
            if reasoning["param"] == "reasoning_effort":
                body["reasoning_effort"] = reasoning["level"]
            elif reasoning["param"] == "enable_thinking":
                body["chat_template_kwargs"] = {"enable_thinking": reasoning["level"] != "off"}
        if request.tools:
            body["tools"] = request.tools
        if request.response_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "hydra_output", "schema": request.response_schema},
            }

        started = time.perf_counter()
        try:
            r = await self.client.post("/chat/completions", json=body, timeout=request.timeout_s)
            r.raise_for_status()
        except Exception as exc:
            raise http_error(exc, model_id) from exc
        elapsed = (time.perf_counter() - started) * 1000

        data = r.json()
        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        usage = data.get("usage") or {}

        tool_calls = []
        for call in message.get("tool_calls") or []:
            fn = call.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError as exc:
                raise ModelError(f"{model_id}: invalid tool arguments", ErrorKind.INVALID_JSON) from exc
            tool_calls.append({"id": call.get("id"), "name": fn.get("name"), "arguments": args})

        structured = None
        if request.response_schema:
            try:
                structured = json.loads(content)
            except json.JSONDecodeError as exc:
                raise ModelError(f"{model_id}: invalid JSON output", ErrorKind.INVALID_JSON) from exc

        return ModelResponse(
            model_id=model_id,
            content=content,
            latency_ms=elapsed,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            tool_calls=tool_calls,
            structured=structured,
        )

    async def health(self) -> bool:
        try:
            r = await self.client.get("/models", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self.client.aclose()
