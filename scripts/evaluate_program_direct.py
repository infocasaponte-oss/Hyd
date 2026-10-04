# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Record raw llama.cpp generations on known regressions and synthetic web fixtures."""
import argparse
import asyncio
import json
from pathlib import Path
import httpx
from hydra.training.verified_corpus import sha256
from hydra.training.program import release_gate


async def evaluate(args):
    build = json.loads(args.manifest.read_text(encoding="utf-8"))
    quarantined = str(build.get("status", "")).startswith("QUARANTINED")
    if quarantined and not args.diagnostic_quarantine:
        raise ValueError("quarantined candidate requires an explicit diagnostic run")
    artifact = Path(build["artifact"])
    if sha256(artifact) != build["sha256"]:
        raise ValueError("artifact hash changed")
    rows = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = {"artifact_sha256": build["sha256"], "dataset_sha256": sha256(args.dataset),
              "model": args.model, "endpoint": args.endpoint, "approved": False,
              "evaluator_sha256": sha256(Path(__file__)),
              "protocol": {"temperature": 0, "seed": 42, "max_tokens": args.max_tokens, "grammar": False},
              "scope": "Known regression or synthetic fixtures; not independent certification",
              "complete": False, "cases": []}
    report["quarantined_diagnostic_only"] = quarantined
    async with httpx.AsyncClient(base_url=args.endpoint, timeout=180) as client:
        props = await client.get("/props")
        props.raise_for_status()
        report["runtime_properties"] = props.json()
        served_path = report["runtime_properties"].get("model_path")
        if not served_path or Path(served_path).resolve() != artifact.resolve():
            raise ValueError("runtime is not serving the declared artifact path")
        for row in rows:
            response = await client.post("/v1/chat/completions", json={"model": args.model,
                "messages": row["messages"][:-1], "temperature": 0, "seed": 42, "max_tokens": args.max_tokens})
            response.raise_for_status()
            output = response.json()["choices"][0]["message"]["content"]
            expected = row["messages"][-1]["content"]
            json_match = None
            try:
                reference_json = json.loads(expected)
                parsed = json.loads(output)
                json_match = json.dumps(parsed, sort_keys=True) == json.dumps(reference_json, sort_keys=True)
            except (ValueError, TypeError):
                pass
            report["cases"].append({"id": row["id"], "output": output, "reference": expected,
                "exact_match": output.strip() == expected.strip(), "json_content_match": json_match,
                "latency_ms": response.elapsed.total_seconds() * 1000,
                "usage": response.json().get("usage", {}),
                "semantic_review": "pending"})
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report.update(complete=True, exact_matches=sum(c["exact_match"] for c in report["cases"]),
                  json_content_matches=sum(c["json_content_match"] is True for c in report["cases"]),
                  total=len(rows), release=release_gate({}))
    if sha256(artifact) != build["sha256"] or sha256(args.dataset) != report["dataset_sha256"]:
        raise ValueError("inputs changed during evaluation")
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"total": report["total"], "exact_matches": report["exact_matches"], "approved": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--diagnostic-quarantine", action="store_true")
    parser.add_argument("--endpoint", default="http://127.0.0.1:18091")
    # 160 is the historical protocol; long literal quotes in grounded sets need more room.
    parser.add_argument("--max-tokens", type=int, default=160)
    asyncio.run(evaluate(parser.parse_args()))
