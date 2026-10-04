# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Minimal OpenAI-compatible chat client for a local model server (llama-server)."""
from __future__ import annotations

import httpx


class LocalLLM:
    def __init__(self, base_url: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/models")
                return response.is_success
        except httpx.HTTPError:
            return False

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        payload = {
            "model": "local",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]
