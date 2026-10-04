# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Identified raw GGUF inference with conservative scoring and separate human review."""
import argparse
import asyncio
import json
import math
import time
from pathlib import Path

import httpx

from hydra.training.evaluate_corpus import candidate_hash, model_identity
from hydra.training.evidence_io import write_json
from hydra.training.finetuning_v8 import read_cases, question, score
from hydra.training.verified_corpus import sha256


async def run(version: int, dataset: Path, output: Path):
    if output.exists():
        raise FileExistsError("existing evidence cannot be overwritten")
    model = f"hydra-instruction-v{version}:latest"
    digest = candidate_hash(Path(f"models/hydra-instruction-v{version}/build-manifest.json"))
    result = dict(model=model, artifact_sha256=digest, dataset_sha256=sha256(dataset),
                  complete=False, approved=False, cases=[], protocol=dict(temperature=0, seed=42,
                  num_ctx=2048, num_predict=512, num_gpu=99), evaluator_sha256=sha256(Path(__file__)),
                  scoring_sha256=sha256(Path("hydra/training/finetuning_v8.py")),
                  scope="Raw inference; semantic cases unscored; not production certification")
    rows = read_cases(dataset)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:11434", timeout=180) as client:
        identity = await model_identity(client, model, digest)
        result["identity"] = identity
        for row in rows:
            started = time.perf_counter()
            case = dict(id=row["id"], prompt=question(row), reference=row.get("answer",row.get("expected_response")),
                        category=row.get("category"), subtype=row.get("subtype"), passed=None)
            response = await client.post("/api/chat", json=dict(model=model, stream=False,
                messages=[dict(role="system", content="Eres HYDRA. Sigue la instrucción del usuario sin añadir datos no proporcionados."),
                          dict(role="user", content=question(row))], options=result["protocol"], keep_alive="5m"))
            response.raise_for_status()
            body = response.json()
            if body.get("eval_count", 0) <= 0:
                raise ValueError("no real generated tokens")
            case.update(output=body["message"]["content"], passed=score(row, body["message"]["content"]),
                        eval_count=body["eval_count"], done_reason=body.get("done_reason"),
                        latency_ms=1000*(time.perf_counter()-started))
            result["cases"].append(case)
            write_json(output, result)
            print(f"v{version} {len(result['cases'])}/{len(rows)}", flush=True)
        if await model_identity(client, model, digest) != identity:
            raise ValueError("candidate changed")
        response = await client.get("/api/ps")
        response.raise_for_status()
        resident = [m for m in response.json()["models"] if m["name"] == identity["name"]]
        if len(resident) != 1 or resident[0].get("size_vram", 0) <= 0:
            raise ValueError("candidate not GPU resident")
        result["gpu_resident"] = resident[0]
    if sha256(dataset) != result["dataset_sha256"]:
        raise ValueError("dataset changed")
    scored = [c for c in result["cases"] if c["passed"] is not None]
    result.update(complete=True, total=len(rows), automatically_scored=len(scored),
                  automatic_passes=sum(c["passed"] for c in scored), human_review_required=len(rows)-len(scored))
    write_json(output, result)


def compare(left: Path, right: Path, output: Path):
    if output.exists():
        raise FileExistsError("comparison evidence cannot be overwritten")
    a,b = [json.loads(p.read_text(encoding="utf-8")) for p in (left,right)]
    if not a["complete"] or not b["complete"]:
        raise ValueError("incomplete evaluation")
    for field in ("dataset_sha256", "protocol", "scoring_sha256", "evaluator_sha256"):
        if a[field] != b[field]:
            raise ValueError(f"comparison mismatch: {field}")
    if a["identity"]["details"]["quantization_level"] != b["identity"]["details"]["quantization_level"]:
        raise ValueError("different quantization")
    if [c["id"] for c in a["cases"]] != [c["id"] for c in b["cases"]]:
        raise ValueError("case identifiers differ")
    wins=losses=0
    changes=[]
    for x,y in zip(a["cases"],b["cases"]):
        if x["passed"] is None or y["passed"] is None:
            continue
        wins += not x["passed"] and y["passed"]
        losses += x["passed"] and not y["passed"]
        if x["passed"] != y["passed"]:
            changes.append(dict(id=x["id"], baseline=x["passed"], candidate=y["passed"]))
    n=wins+losses
    p=min(1.,2*sum(math.comb(n,i) for i in range(min(wins,losses)+1))/2**n) if n else 1.
    write_json(output,dict(baseline=a["model"],candidate=b["model"],baseline_passes=a["automatic_passes"],
                          candidate_passes=b["automatic_passes"], automatically_scored=a["automatically_scored"],
                          wins=wins,losses=losses,mcnemar_exact_p=p,changes=changes,approved=False,
                          human_review_required=b["human_review_required"],
                          scope="Automatic subset only; semantic questions excluded from automatic scoring"))


def rescore(source: Path, dataset: Path, output: Path):
    if output.exists():
        raise FileExistsError("preserve existing evidence")
    result = json.loads(source.read_text(encoding="utf-8"))
    if not result["complete"] or result["dataset_sha256"] != sha256(dataset):
        raise ValueError("incomplete or mismatched raw evidence")
    rows = read_cases(dataset)
    if [r["id"] for r in rows] != [r["id"] for r in result["cases"]]:
        raise ValueError("case order changed")
    for row,case in zip(rows,result["cases"]):
        if question(row) != case["prompt"] or row.get("answer",row.get("expected_response")) != case["reference"]:
            raise ValueError("source case changed")
        case["passed"] = score(row,case["output"])
    result.update(raw_source_sha256=sha256(source),original_evaluator_sha256=result["evaluator_sha256"],
                  original_scoring_sha256=result["scoring_sha256"],
                  evaluator_sha256=sha256(Path(__file__)),scoring_sha256=sha256(Path("hydra/training/finetuning_v8.py")),
                  scoring_note="Same preserved raw inference; accepts exact pack identity and equal numbers with compatible units")
    scored = [c for c in result["cases"] if c["passed"] is not None]
    result.update(automatically_scored=len(scored),automatic_passes=sum(c["passed"] for c in scored))
    write_json(output,result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, choices=[7,8])
    parser.add_argument("--dataset", type=Path, default=Path("data/hydra-instruction-v8/supplied-development.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", type=Path, nargs=2)
    parser.add_argument("--rescore", type=Path)
    args = parser.parse_args()
    if args.rescore:
        rescore(args.rescore,args.dataset,args.output)
    elif args.compare:
        compare(*args.compare, args.output)
    elif args.version:
        asyncio.run(run(args.version,args.dataset,args.output))
    else:
        parser.error("version or compare required")
