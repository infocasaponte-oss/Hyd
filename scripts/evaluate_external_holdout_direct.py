# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""External holdout (user-supplied references) through llama-server, for any candidate build.

Same protocol as scripts/evaluate_external_holdout.py (system prompt, temperature 0, seed 42,
160 tokens, automatic_match) but served by the pinned llama.cpp runtime and bound to the exact
GGUF by hash, so candidates from different lineages are compared on the same runtime.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_external_holdout import automatic_match  # noqa: E402  (sibling script, same criterion)
from hydra.training.verified_corpus import sha256  # noqa: E402

SYSTEM = "Eres HYDRA. Sigue la instrucción del usuario sin añadir datos no proporcionados."


async def evaluate(manifest: Path, output: Path, model: str, endpoint: str) -> dict:
    root = Path("data/external-evaluation-v2")
    data = root / "cases.json"
    if sha256(data) != json.loads((root / "manifest.json").read_text(encoding="utf-8"))["cases_sha256"]:
        raise ValueError("external test changed")
    if output.exists():
        raise FileExistsError("existing evaluated holdout cannot be overwritten")
    build = json.loads(manifest.read_text(encoding="utf-8"))
    artifact = Path(build["artifact"])
    if sha256(artifact) != build["sha256"]:
        raise ValueError("artifact hash changed")
    result = {"model": model, "artifact_sha256": build["sha256"], "dataset_sha256": sha256(data), "complete": False,
              "approved": False, "independent_test": False, "runtime": "llama-server", "endpoint": endpoint,
              "protocol": {"temperature": 0, "seed": 42, "max_tokens": 160, "system": SYSTEM},
              "scope": "user supplied references; semantic and ambiguous cases require human review", "cases": []}
    async with httpx.AsyncClient(base_url=endpoint, timeout=180) as client:
        props = (await client.get("/props")).json()
        if Path(props.get("model_path", "")).resolve() != artifact.resolve():
            raise ValueError("runtime is not serving the declared artifact")
        for row in json.loads(data.read_text(encoding="utf-8-sig")):
            case = {"id": row["id"], "automatic_match": False}
            try:
                response = await client.post("/v1/chat/completions", json={
                    "model": model, "temperature": 0, "seed": 42, "max_tokens": 160,
                    "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": row["prompt"]}]})
                response.raise_for_status()
                case["output"] = response.json()["choices"][0]["message"]["content"]
                case["automatic_match"] = automatic_match(case["output"], row["expected_response"])
            except Exception as exc:  # recorded per case, as in the Ollama evaluator
                case["error"] = type(exc).__name__
            result["cases"].append(case)
    if sha256(artifact) != build["sha256"]:
        raise ValueError("artifact changed during evaluation")
    result.update(complete=True, total=len(result["cases"]),
                  automatic_matches=sum(c["automatic_match"] for c in result["cases"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {k: result[k] for k in ("model", "total", "automatic_matches")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:18091")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(evaluate(args.manifest, args.output, args.model, args.endpoint))))
