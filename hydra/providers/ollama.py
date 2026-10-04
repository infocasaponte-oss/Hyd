# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Ollama native provider (/api/chat)."""

from __future__ import annotations

import base64
import json
import time

import httpx

from hydra.core.contracts import ModelRequest, ModelResponse
from hydra.core.errors import ErrorKind, ModelError
from hydra.providers.base import ModelProvider, http_error


def ollama_model_key(name: str) -> str:
    """Ollama treats an untagged model name as name:latest."""
    return name if ":" in name else f"{name}:latest"


class OllamaProvider(ModelProvider):
    def __init__(self, base_url: str = "http://localhost:11434", timeout_s: float = 120) -> None:
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s)

    async def generate(self, model_id: str, request: ModelRequest) -> ModelResponse:
        body: dict = {
            "model": model_id,
            "messages": [await self._message(m) for m in request.messages],
            "stream": False,
            "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
        }
        opts = dict(request.metadata.get("runtime_options") or {})
        if "keep_alive" in opts:
            body["keep_alive"] = opts.pop("keep_alive")
        if "think" in opts:
            value = opts.pop("think")
            if not isinstance(value, bool):
                raise ValueError("runtime_options.think must be boolean")
            body["think"] = value
        body["options"].update(opts)
        if reasoning := request.metadata.get("reasoning"):
            body["think"] = reasoning["level"] != "off"
        if request.tools:
            body["tools"] = request.tools
        if request.response_schema:
            body["format"] = request.response_schema

        started = time.perf_counter()
        try:
            r = await self.client.post("/api/chat", json=body, timeout=request.timeout_s)
            r.raise_for_status()
        except Exception as exc:
            raise http_error(exc, model_id) from exc
        elapsed = (time.perf_counter() - started) * 1000

        data = r.json()
        message = data.get("message", {})
        content = message.get("content") or ""

        tool_calls = [
            {
                "id": None,
                "name": c.get("function", {}).get("name"),
                "arguments": c.get("function", {}).get("arguments") or {},
            }
            for c in message.get("tool_calls") or []
        ]

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
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            tool_calls=tool_calls,
            structured=structured,
        )

    async def _message(self, m: dict) -> dict:
        """Ollama wants raw base64 images; tool-call arguments as objects."""
        out = {k: v for k, v in m.items() if k not in ("images", "tool_calls", "tool_call_id")}
        if m.get("tool_calls"):
            out["tool_calls"] = [{"function": {"name": c["function"]["name"],
                                               "arguments": json.loads(c["function"]["arguments"] or "{}")}}
                                 for c in m["tool_calls"]]
        if images := m.get("images"):
            out["images"] = [await self._b64(img) for img in images]
        return out

    async def _b64(self, image: str) -> str:
        if image.startswith("data:"):
            return image.split(",", 1)[1]
        if image.startswith(("http://", "https://")):
            r = await self.client.get(image, timeout=30)
            r.raise_for_status()
            return base64.b64encode(r.content).decode()
        return image  # already base64

    async def health(self) -> bool:
        try:
            r = await self.client.get("/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    async def installed_models(self) -> set[str] | None:
        """Models present in this Ollama instance (normalised to name:tag); None if unreachable."""
        try:
            r = await self.client.get("/api/tags", timeout=5)
            r.raise_for_status()
            return {ollama_model_key(m.get("name") or m.get("model", "")) for m in r.json().get("models", [])}
        except Exception:
            return None

    async def close(self) -> None:
        await self.client.aclose()
