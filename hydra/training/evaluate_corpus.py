# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Evaluate a real Ollama model on the frozen coding holdout using Docker."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
import uuid
from pathlib import Path

import httpx

from hydra.tools.sandbox import DockerSandbox
from hydra.training.verified_corpus import sha256


def verification_program(code: str, cases: list[dict]) -> tuple[str, str]:
    """Require completion of all assertions; a zero exit alone is not a pass."""
    if not cases:
        raise ValueError("verification requires test cases")
    marker = "HYDRA_TESTS_COMPLETED_" + uuid.uuid4().hex
    tests = "\n".join(f"assert solve({c['input']!r}) == {c['expected']!r}" for c in cases)
    return code + "\n" + tests + f"\nprint({marker!r})\n", marker


def candidate_hash(manifest_path: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "CANDIDATE_REQUIRES_EVALUATION":
        raise ValueError("build is not a completed candidate")
    artifact = Path(manifest["artifact"])
    if not artifact.is_file() or sha256(artifact) != manifest["sha256"]:
        raise ValueError("candidate artifact does not match build manifest")
    return manifest["sha256"]


async def model_identity(client: httpx.AsyncClient, model: str, expected_hash: str | None) -> dict:
    response = await client.get("/api/tags")
    response.raise_for_status()
    canonical = model if ":" in model.rsplit("/", 1)[-1] else model + ":latest"
    matches = [item for item in response.json().get("models", [])
               if item.get("name") == canonical or item.get("model") == canonical]
    if len(matches) != 1 or not matches[0].get("digest"):
        raise ValueError("cannot resolve an unambiguous local model digest")
    show = await client.post("/api/show", json={"model": model})
    show.raise_for_status()
    info = show.json()
    # Ollama's generated Modelfile identifies the imported GGUF blob in FROM.
    source = re.search(r'^FROM\s+"?([^"\r\n]+)"?\s*$', info.get("modelfile", ""), re.M)
    blob = re.search(r"sha256[-:]([0-9a-f]{64})$", source.group(1).strip()) if source else None
    artifact_hash = blob.group(1) if blob else None
    if expected_hash and artifact_hash != expected_hash:
        raise ValueError("served GGUF does not match candidate artifact hash")
    return {"name": canonical, "digest": matches[0]["digest"],
            "artifact_sha256": artifact_hash, "details": info.get("details", {})}


async def evaluate(model: str, corpus: Path, output: Path, limit: int = 0,
                   build_manifest: Path | None = None) -> dict:
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    expected_hash = candidate_hash(build_manifest) if build_manifest else None
    dataset = corpus/"test.jsonl"
    manifest = json.loads((corpus/"manifest.json").read_text(encoding="utf-8"))
    if sha256(dataset) != manifest["files"][dataset.name]["sha256"]:
        raise ValueError("holdout hash mismatch")
    rows = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines()]
    if limit:
        rows = rows[:limit]
    if not rows:
        raise ValueError("empty holdout")
    sandbox = DockerSandbox()
    result = {"model":model,"dataset_sha256":sha256(dataset),"subset":bool(limit),
              "artifact_sha256":expected_hash, "status":"EVALUATING",
              "approved":False,"cases":[]}
    output.parent.mkdir(parents=True,exist_ok=True)
    def save():
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
        temporary.replace(output)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:11434",timeout=180) as client:
        identity = await model_identity(client, model, expected_hash)
        result["model_identity"] = identity
        save()
        for row in rows:
            start = time.perf_counter()
            case = {"id":row["id"],"family":row["family"],"passed":False}
            try:
                response = await client.post("/api/chat",json={"model":model,"stream":False,
                    "messages":row["messages"][:-1],
                    "options":{"temperature":0,"seed":42,"num_predict":256,"num_ctx":2048}})
                response.raise_for_status()
                payload = response.json()
                answer = payload["message"]["content"]
                match = re.search(r"```(?:python|py)?\s*\n(.*?)```",answer,re.S)
                code = match.group(1) if match else answer
                program, marker = verification_program(code, row["verification"]["cases"])
                execution = await sandbox.execute_python(program,timeout=15)
                completed = marker in execution.stdout.splitlines()
                case.update(passed=execution.exit_code == 0 and completed, checks_completed=completed, output=answer,
                            stderr=execution.stderr[-1000:],tokens=payload.get("eval_count"))
                duration = payload.get("eval_duration", 0)
                case["generation_duration_ms"] = duration / 1_000_000
                case["generation_tokens_per_second"] = (
                    payload.get("eval_count", 0) * 1_000_000_000 / duration if duration > 0 else None)
                # Non-streaming elapsed time is not TTFT; do not label it as such.
            except Exception as exc:
                case["error"] = f"{type(exc).__name__}: {exc}"
            case["latency_ms"] = round((time.perf_counter()-start)*1000,1)
            result["cases"].append(case)
            result["score"] = sum(c["passed"] for c in result["cases"])/len(result["cases"])
            save()
        try:
            if await model_identity(client, model, expected_hash) != identity:
                raise ValueError("served model changed during evaluation")
        except Exception as exc:
            result.update(status="INVALID_MODEL_IDENTITY", error=f"{type(exc).__name__}: {exc}")
            save()
            raise
    result["status"] = "EVALUATED_SUBSET" if limit else "EVALUATED"
    save()
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model",required=True)
    p.add_argument("--corpus",type=Path,default=Path("data/hydra-corpus-v1"))
    p.add_argument("--output",type=Path,default=Path("data/evaluations/holdout.json"))
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--build-manifest",type=Path,help="Verify the served GGUF against this completed build")
    args = p.parse_args()
    result = asyncio.run(evaluate(args.model,args.corpus,args.output,args.limit,args.build_manifest))
    print(json.dumps({"model": result["model"], "status": result["status"], "score": result.get("score"),
                      "cases": len(result["cases"]), "approved": False, "report": str(args.output)}, indent=2))
