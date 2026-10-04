# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Record real direct-runtime responses; never promote based on this smoke test."""
import asyncio
import json
from pathlib import Path

from hydra.core.contracts import ModelRequest
from hydra.providers.openai_compatible import OpenAICompatibleProvider
from hydra.workers.reasoner import ReasonerWorker


async def main():
    provider = OpenAICompatibleProvider("http://127.0.0.1:18090/v1")
    cases = [
        ("identity", "Que é HYDRA e cal é a procedencia do modelo base?", None),
        ("instruction", "Responde exactamente: HYDRA", None),
        ("json", 'Devuelve solo JSON con "ok" igual a true.',
         {"type": "object", "properties": {"ok": {"type": "boolean"}},
          "required": ["ok"], "additionalProperties": False}),
    ]
    results = []
    try:
        for name, prompt, schema in cases:
            response = await provider.generate("hydra-instruction-v8", ModelRequest(
                messages=[{"role": "system", "content": ReasonerWorker.system_prompt
                           + " This candidate uses Qwen-derived weights fine-tuned for HYDRA."},
                          {"role": "user", "content": prompt}],
                temperature=0, max_tokens=128, response_schema=schema))
            results.append({"case": name, "prompt": prompt, "output": response.content,
                            "latency_ms": response.latency_ms})
    finally:
        await provider.close()
    report = {"backend": "llamacpp", "production_approved": False, "responses": results}
    Path("docs/evidence/hydra-direct-smoke.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
