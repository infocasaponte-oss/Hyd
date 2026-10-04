# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Real raw GGUF answers for user review; external cases are never training data."""
import asyncio
import json
import re
from pathlib import Path

import httpx
from hydra.training.evaluate_corpus import candidate_hash, model_identity
from hydra.training.verified_corpus import sha256
from hydra.training.evidence_io import write_json
from hydra.training.json_match import matching_json


def automatic_match(text,expected):
    try:
        reference=json.loads(expected)
        cleaned=re.sub(r"^```(?:json)?\s*([\s\S]*?)\s*```$",r"\1",text.strip())
        return matching_json(json.loads(cleaned),reference)
    except (ValueError,TypeError):
        return text.strip()==expected.strip()


async def evaluate(output=Path("docs/evidence/external-evaluation-v5.json"), version=5):
    if version not in (5,6,7,8):
        raise ValueError("unsupported candidate version")
    root=Path("data/external-evaluation-v2")
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    data=root/"cases.json"
    if sha256(data)!=manifest["cases_sha256"]:
        raise ValueError("external test changed")
    model=f"hydra-instruction-v{version}:latest"
    digest=candidate_hash(Path(f"models/hydra-instruction-v{version}/build-manifest.json"))
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():
        raise FileExistsError("existing evaluated holdout cannot be overwritten")
    result=dict(model=model,artifact_sha256=digest,dataset_sha256=sha256(data),complete=False,
                approved=False,independent_test=False,cases=[],scope="user supplied references; semantic and ambiguous cases require human review")
    def save():
        write_json(output,result)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:11434",timeout=120) as client:
        identity=await model_identity(client,model,digest)
        result["identity"]=identity
        for row in json.loads(data.read_text(encoding="utf-8")):
            case=dict(id=row["id"],automatic_match=False)
            try:
                r=await client.post("/api/chat",json=dict(model=model,stream=False,
                    messages=[dict(role="system",content="Eres HYDRA. Sigue la instrucción del usuario sin añadir datos no proporcionados."),
                              dict(role="user",content=row["prompt"])],
                    options=dict(temperature=0,seed=42,num_ctx=2048,num_predict=160,num_gpu=99),keep_alive="5m"))
                r.raise_for_status()
                case["output"]=r.json()["message"]["content"]
                case["automatic_match"]=automatic_match(case["output"],row["expected_response"])
            except Exception as e:
                case["error"]=type(e).__name__
            result["cases"].append(case)
            save()
        if await model_identity(client,model,digest)!=identity:
            raise ValueError("candidate changed")
    result.update(complete=True,total=len(result["cases"]),automatic_matches=sum(c["automatic_match"] for c in result["cases"]))
    save()
    print(json.dumps({k:v for k,v in result.items() if k not in ("cases","identity")},indent=2))


if __name__ == "__main__":
    asyncio.run(evaluate())
