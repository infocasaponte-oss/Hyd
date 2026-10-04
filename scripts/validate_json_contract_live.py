# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Uncached end-to-end JSON calls; expected answers are used only after inference."""
import argparse
import asyncio
import json
from pathlib import Path

import httpx

from hydra.training.evaluate_corpus import candidate_hash
from hydra.training.generation_reliability import check
from hydra.training.evidence_io import write_json
from hydra.training.verified_corpus import sha256
import hydra.workers.reasoner as policy


async def validate(studio, corpus, manifest, output, version=7):
    if output.exists():
        raise FileExistsError("fresh evidence required")
    data=corpus/"validation.jsonl"
    pinned=json.loads((corpus/"manifest.json").read_text(encoding="utf-8"))
    if sha256(data)!=pinned["files"][data.name]["sha256"]:
        raise ValueError("dataset changed")
    rows=[row for row in map(json.loads,data.read_text(encoding="utf-8").splitlines()) if row["family"]=="json"]
    report=dict(artifact_sha256=candidate_hash(manifest),dataset_sha256=sha256(data),
                schema_policy_sha256=sha256(Path(policy.__file__)),cases=[],complete=False,approved=False,
                scope="real configured engine on known synthetic JSON development, not independent human test")
    async with httpx.AsyncClient(timeout=90) as client:
        for row in rows:
            case=dict(id=row["id"],passed=False)
            try:
                for retry in range(3):
                    response=await client.post(studio.rstrip("/")+"/v1/hydra",json=dict(
                        use_cache=False,messages=row["messages"][:-1]))
                    if response.status_code!=429:
                        break
                    case["rate_limit_retries"]=retry+1
                    await asyncio.sleep(60)
                case["http_status"]=response.status_code
                response.raise_for_status()
                body=response.json()
                meta=body["meta"]
                case.update(output=body["answer"],meta=meta)
                case["passed"]=bool(check(row,body["answer"]) and not meta.get("cached")
                    and f"hydra-instruction-v{version}-candidate" in meta.get("models_used",[]))
            except Exception as exc:
                case["error"]=type(exc).__name__
            report["cases"].append(case)
            write_json(output,report)
            await asyncio.sleep(1.1)
    report.update(complete=True,total=len(rows),correct=sum(c["passed"] for c in report["cases"]))
    report["accuracy"]=report["correct"]/report["total"]
    write_json(output,report)
    print(json.dumps({k:v for k,v in report.items() if k!="cases"},indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--studio",default="http://127.0.0.1:18087")
    parser.add_argument("--corpus",type=Path,default=Path("data/hydra-instruction-v7-contract-v2"))
    parser.add_argument("--manifest",type=Path,default=Path("models/hydra-instruction-v7/build-manifest.json"))
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--version",type=int,choices=[7,8],default=7)
    args=parser.parse_args()
    asyncio.run(validate(args.studio,args.corpus,args.manifest,args.output,args.version))
