# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Bounded 15-minute real GPU soak: no cache, identified GGUF, health and VRAM snapshots."""
import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx

from hydra.training.evaluate_corpus import candidate_hash, model_identity
from hydra.training.generation_reliability import check
from hydra.training.evidence_io import write_json


async def validate(model, manifest, corpus, output, seconds=900, studio=None):
    if seconds < 900:
        raise ValueError("prolonged soak requires at least 900 seconds")
    if output.exists():
        raise FileExistsError("versioned evidence required")
    digest = candidate_hash(manifest)
    rows = [json.loads(line) for line in (corpus/"validation.jsonl").read_text(encoding="utf-8").splitlines()]
    # Use three well-defined output contracts; reasoning failures are separately evaluated.
    examples = [next(r for r in rows if r["family"] == family) for family in ("literal","json","sum")]
    result = dict(model=model,artifact_sha256=digest,complete=False,approved=False,
                  scope="bounded synthetic regression soak; not general production certification",
                  required_duration_s=seconds,calls=[],snapshots=[],engine_calls=[])
    def save():
        write_json(output,result)
    started=time.monotonic()
    previous,seen=0,{}
    async with httpx.AsyncClient(base_url="http://127.0.0.1:11434",timeout=60) as client:
        identity=await model_identity(client,model,digest)
        result["identity"]=identity
        save()
        while time.monotonic()-started < seconds:
            i=len(result["calls"])
            row=examples[i%len(examples)]
            start=time.perf_counter()
            call=dict(id=row["id"],passed=False)
            try:
                r=await client.post("http://127.0.0.1:11434/api/chat",json=dict(model=model,stream=False,
                    messages=row["messages"][:-1],keep_alive="5m",
                    options=dict(temperature=0,seed=42,num_ctx=2048,num_predict=96,num_gpu=99)))
                r.raise_for_status()
                body=r.json()
                text=body["message"]["content"]
                if body.get("eval_count",0) <= 0:
                    raise ValueError("inference did not evaluate output tokens")
                call.update(passed=check(row,text),output=text,eval_count=body["eval_count"],
                            stable=text==seen.setdefault(row["id"],text))
            except Exception as e:
                call["error"]=type(e).__name__
            call["latency_ms"]=(time.perf_counter()-start)*1000
            result["calls"].append(call)
            elapsed=time.monotonic()-started
            if elapsed-previous >= 30 or i == 0:
                ps=await client.get("http://127.0.0.1:11434/api/ps")
                ps.raise_for_status()
                models=[m for m in ps.json().get("models",[]) if m.get("name") == identity["name"]]
                if len(models)!=1 or models[0].get("size_vram",0)<=0:
                    raise ValueError("candidate not resident in GPU")
                result["snapshots"].append(dict(elapsed_s=elapsed,size_vram=models[0]["size_vram"]))
                if await model_identity(client,model,digest)!=identity:
                    raise ValueError("candidate identity changed")
                if studio:
                    engine=dict(passed=False)
                    try:
                        r=await client.post(studio.rstrip("/")+"/v1/hydra",json=dict(use_cache=False,
                            messages=[dict(role="user",content=f"Devuelve solo JSON válido con id={85000+i} y activo=false. Usa un booleano para activo.")]))
                        r.raise_for_status()
                        body=r.json()
                        meta=body["meta"]
                        if model.split(":")[0]+"-candidate" not in meta.get("models_used",[]):
                            raise ValueError("engine used a different model or a deterministic solver")
                        parsed=json.loads(body["answer"])
                        engine.update(passed=parsed==dict(id=85000+i,activo=False) and type(parsed.get("activo")) is bool,
                                      cached=meta.get("cached"),models_used=meta.get("models_used"),latency_ms=meta.get("latency_ms"))
                        if engine["cached"]:
                            raise ValueError("cached engine response is not a real inference")
                    except Exception as e:
                        engine["error"]=type(e).__name__
                        engine["passed"]=False
                    result["engine_calls"].append(engine)
                previous=elapsed
                result["elapsed_s"]=elapsed
                save()
                print(json.dumps(dict(elapsed_s=round(elapsed),calls=len(result["calls"]),errors=sum("error" in c for c in result["calls"]))),flush=True)
            await asyncio.sleep(.5)
        result["final_identity"]=await model_identity(client,model,digest)
    calls=result["calls"]
    latencies=sorted(c["latency_ms"] for c in calls)
    resident=[s["size_vram"] for s in result["snapshots"]]
    result.update(complete=True,elapsed_s=time.monotonic()-started,total=len(calls),
                  failures=sum("error" in c for c in calls),correct=sum(c["passed"] for c in calls),
                  unstable=sum(not c.get("stable",False) for c in calls),
                  median_ms=statistics.median(latencies),p95_ms=latencies[int((len(latencies)-1)*.95)],
                  vram_growth_bytes=resident[-1]-resident[0],vram_min_bytes=min(resident),vram_max_bytes=max(resident))
    result["soak_gate_passed"]=bool(result["elapsed_s"]>=seconds and len(calls)>=300 and result["failures"]==0
        and result["correct"]==len(calls) and result["unstable"]==0 and result["final_identity"]==identity
        and result["vram_growth_bytes"]<=64*1024*1024 and (not studio or all(c["passed"] for c in result["engine_calls"])))
    save()
    print(json.dumps({k:v for k,v in result.items() if k not in ("calls","engine_calls","identity","final_identity","snapshots")},indent=2))


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--model",required=True)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--corpus",type=Path,default=Path("data/hydra-instruction-v5"))
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--seconds",type=int,default=900)
    p.add_argument("--studio")
    a=p.parse_args()
    asyncio.run(validate(a.model,a.manifest,a.corpus,a.output,a.seconds,a.studio))
