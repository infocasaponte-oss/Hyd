# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Measure local streaming inference; diagnostic evidence, not a promotion benchmark."""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx

from hydra.training.evaluate_corpus import candidate_hash, model_identity


async def measure(model: str, manifest: Path, output: Path, repetitions: int = 5) -> dict:
    if repetitions < 2:
        raise ValueError("at least two repetitions are required")
    expected = candidate_hash(manifest)
    result = {"status": "MEASURING", "approved": False, "samples": [],
              "scope": "Ollama streaming, fixed prompt, first run separate from subsequent runs; not HYDRA gateway",
              "peak_vram_mb": None}
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        temp = output.with_suffix(".tmp")
        temp.write_text(json.dumps(result, indent=2), encoding="utf-8")
        temp.replace(output)

    async with httpx.AsyncClient(base_url="http://127.0.0.1:11434", timeout=180) as client:
        identity = await model_identity(client, model, expected)
        result["model_identity"] = identity
        save()
        try:
            for index in range(repetitions):
                first = None
                final = None
                start = time.perf_counter()
                async with client.stream("POST", "/api/chat", json={
                    "model": model, "stream": True,
                    "messages": [{"role": "user", "content": "Escribe solo una función Python solve(xs) que sume xs."}],
                    "options": {"temperature": 0, "seed": 42, "num_predict": 128, "num_ctx": 2048},
                }) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        if chunk.get("error"):
                            raise RuntimeError(chunk["error"])
                        if first is None and chunk.get("message", {}).get("content"):
                            first = (time.perf_counter() - start) * 1000
                        if chunk.get("done"):
                            final = chunk
                if first is None or final is None or final.get("eval_duration", 0) <= 0:
                    raise ValueError("incomplete stream or missing generation measurements")
                result["samples"].append({"index": index, "ttft_ms": first,
                    "elapsed_ms": (time.perf_counter() - start) * 1000,
                    "generated_tokens": final["eval_count"],
                    "tokens_per_second": final["eval_count"] * 1e9 / final["eval_duration"],
                    "load_ms": final.get("load_duration", 0) / 1e6})
                save()
            if await model_identity(client, model, expected) != identity:
                raise ValueError("model identity changed")
            repeated = result["samples"][1:]
            result.update(status="MEASURED_DIAGNOSTIC",
                          repeated_median_ttft_ms=statistics.median(x["ttft_ms"] for x in repeated),
                          repeated_median_tokens_per_second=statistics.median(x["tokens_per_second"] for x in repeated))
        except Exception as exc:
            result.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
            save()
            raise
    save()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="hydra-local")
    parser.add_argument("--build-manifest", type=Path, default=Path("models/hydra-pilot/build-manifest.json"))
    parser.add_argument("--output", type=Path, default=Path("data/evaluations/hydra-streaming.json"))
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(measure(args.model, args.build_manifest, args.output, args.repetitions)), indent=2))
