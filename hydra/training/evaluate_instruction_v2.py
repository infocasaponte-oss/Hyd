# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Exact-output and JSON checks for an identified Ollama candidate; no automatic promotion."""
import argparse
import asyncio
import json
import time
from pathlib import Path

import httpx

from hydra.training.evaluate_corpus import candidate_hash, model_identity
from hydra.training.verified_corpus import sha256
from hydra.training.evidence_io import write_json
from hydra.workers.reasoner import requested_json_schema


async def evaluate(model: str, output: Path, manifest_path: Path | None = None,
                   corpus: Path = Path("data/hydra-instruction-v2"), typed_state_json: bool = False) -> dict:
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    test = corpus / "test.jsonl"
    if sha256(test) != manifest["files"][test.name]["sha256"]:
        raise ValueError("test partition changed")
    expected_hash = candidate_hash(manifest_path) if manifest_path else None
    rows = [json.loads(line) for line in test.read_text(encoding="utf-8").splitlines()]
    result = {"model": model, "dataset_sha256": sha256(test), "cases": [], "approved": False,
              "protocol": "typed-state-json" if typed_state_json else "raw-generation",
              "scope": "synthetic exact-output and JSON test; requires separate coding and human evaluation"}
    def save():
        write_json(output,result)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:11434", timeout=120) as client:
        identity = await model_identity(client, model, expected_hash)
        result["identity"] = identity
        save()
        for row in rows:
            start = time.perf_counter()
            case = {"id": row["id"], "kind": row["verification"]["kind"], "passed": False}
            try:
                body = {"model": model, "stream": False,
                    "messages": row["messages"][:-1], "options": {"temperature": 0, "seed": 42,
                    "num_ctx": 2048, "num_predict": 96, "num_gpu": 99}}
                if typed_state_json:
                    schema=requested_json_schema(body["messages"],typed_state_json=True)
                    if schema:
                        body["format"]=schema
                        case["response_schema"]=schema
                response = await client.post("/api/chat", json=body)
                response.raise_for_status()
                text = response.json()["message"]["content"].strip()
                expected = row["verification"]["expected"]
                case["output"] = text
                if case["kind"] == "json":
                    parsed = json.loads(text)
                    case["passed"] = (isinstance(parsed, dict) and parsed == json.loads(expected)
                                      and type(parsed.get("id")) is int and type(parsed.get("activo")) is bool)
                else:
                    case["passed"] = text == expected
            except Exception as exc:
                case["error"] = type(exc).__name__
            case["latency_ms"] = round((time.perf_counter()-start)*1000, 2)
            result["cases"].append(case)
            save()
        if await model_identity(client, model, expected_hash) != identity:
            raise ValueError("served candidate changed during evaluation")
    result.update(correct=sum(c["passed"] for c in result["cases"]), total=len(rows), status="EVALUATED")
    result["accuracy"] = result["correct"] / result["total"]
    result["instruction_gate_passed"] = result["accuracy"] > .90
    save()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--corpus", type=Path, default=Path("data/hydra-instruction-v2"))
    parser.add_argument("--typed-state-json", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(evaluate(args.model, args.output, args.manifest, args.corpus, args.typed_state_json))
    print(json.dumps({k: v for k, v in result.items() if k not in ("cases", "identity")}, indent=2))
