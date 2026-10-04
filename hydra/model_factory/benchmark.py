# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Benchmark harness: tokens/s, TTFT, load time, RAM/VRAM, quality, context degradation,
concurrency. Measured on the real runtime (Ollama timings are exact; OpenAI-compatible
servers are measured by streaming)."""

from __future__ import annotations

import asyncio
import json
import time

import httpx

from hydra.model_factory.manifest import BenchmarkResult

PROMPTS = [
    "Explain in four sentences how a hash map works.",
    "Escribe una función en Python que devuelva los n primeros números de Fibonacci.",
    "List five differences between TCP and UDP.",
]

NEEDLE = "The secret code word is PERSIMMON-42."


def _haystack(words: int = 2500) -> str:
    filler = ("HYDRA routes requests between models according to capability, latency, cost and privacy. "
              "Memories are verified before becoming canonical. ") * (words // 25)
    return f"{NEEDLE}\n\n{filler}\n\nQuestion: what is the secret code word? Answer with the code only."


class OllamaBenchmark:
    def __init__(self, base_url: str = "http://localhost:11434", timeout: float = 600) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def _generate(self, client: httpx.AsyncClient, model: str, prompt: str, num_predict: int = 128,
                        num_ctx: int | None = None) -> dict:
        options = {"temperature": 0, "num_predict": num_predict}
        if num_ctx:
            options["num_ctx"] = num_ctx
        r = await client.post(f"{self.base_url}/api/generate",
                              json={"model": model, "prompt": prompt, "stream": False, "options": options,
                                    "keep_alive": "5m"})
        r.raise_for_status()
        return r.json()

    async def run(self, model: str, variant_id: str = "", artifact_id: str = "", runs: int = 3,
                  context_test: bool = True, concurrency: int = 2) -> BenchmarkResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await client.post(f"{self.base_url}/api/generate", json={"model": model, "keep_alive": 0})  # unload
            cold = await self._generate(client, model, "Hi", num_predict=1)
            load_ms = cold.get("load_duration", 0) / 1e6

            tps, ptps, ttft = [], [], []
            for i in range(runs):
                r = await self._generate(client, model, PROMPTS[i % len(PROMPTS)])
                if r.get("eval_duration"):
                    tps.append(r["eval_count"] / (r["eval_duration"] / 1e9))
                if r.get("prompt_eval_duration"):
                    ptps.append(r.get("prompt_eval_count", 0) / (r["prompt_eval_duration"] / 1e9))
                    ttft.append((r.get("load_duration", 0) + r["prompt_eval_duration"]) / 1e6)

            ram = vram = None
            ps = (await client.get(f"{self.base_url}/api/ps")).json().get("models", [])
            for m in ps:
                if m.get("name") == model or m.get("model") == model or m.get("name", "").split(":")[0] == model:
                    ram = round(m.get("size", 0) / 1024 ** 3, 2)
                    vram = round(m.get("size_vram", 0) / 1024 ** 3, 2)

            degradation = None
            if context_test:
                r = await self._generate(client, model, _haystack(), num_predict=16, num_ctx=8192)
                degradation = 0.0 if "PERSIMMON" in r.get("response", "").upper() else 1.0

            conc = None
            if concurrency > 1:
                started = time.perf_counter()
                res = await asyncio.gather(*[self._generate(client, model, PROMPTS[0], num_predict=64)
                                             for _ in range(concurrency)], return_exceptions=True)
                wall = time.perf_counter() - started
                tokens = sum(r.get("eval_count", 0) for r in res if isinstance(r, dict))
                conc = round(tokens / wall, 2) if wall else None

        def avg(xs):
            return round(sum(xs) / len(xs), 2) if xs else None

        return BenchmarkResult(artifact_id=artifact_id, variant_id=variant_id, tokens_per_second=avg(tps),
                               prompt_tokens_per_second=avg(ptps), ttft_ms=avg(ttft), load_ms=round(load_ms, 1),
                               ram_gb=ram, vram_gb=vram, context_degradation=degradation,
                               concurrency_tps=conc, runs=runs)


class OpenAIBenchmark:
    """llama-server / vLLM / MLX server: measure TTFT and decode speed by streaming."""

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 600) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.timeout = timeout

    async def _stream(self, client: httpx.AsyncClient, model: str, prompt: str, max_tokens: int = 128):
        started = time.perf_counter()
        first = None
        chunks = 0
        async with client.stream("POST", f"{self.base_url}/chat/completions", headers=self.headers, json={
            "model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "temperature": 0, "stream": True}) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data:") or line.strip() == "data: [DONE]":
                    continue
                delta = json.loads(line[5:])["choices"][0].get("delta", {}).get("content")
                if delta:
                    first = first or time.perf_counter()
                    chunks += 1
        end = time.perf_counter()
        ttft = ((first or end) - started) * 1000
        tps = chunks / (end - first) if first and end > first else None
        return ttft, tps

    async def run(self, model: str, variant_id: str = "", artifact_id: str = "", runs: int = 3) -> BenchmarkResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = [await self._stream(client, model, PROMPTS[i % len(PROMPTS)]) for i in range(runs)]
        ttfts = [r[0] for r in res]
        tpss = [r[1] for r in res if r[1]]
        return BenchmarkResult(artifact_id=artifact_id, variant_id=variant_id,
                               ttft_ms=round(sum(ttfts) / len(ttfts), 1),
                               tokens_per_second=round(sum(tpss) / len(tpss), 2) if tpss else None, runs=runs)
