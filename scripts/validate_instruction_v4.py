# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compare GGUF candidate with deployed baseline; never promotes either model."""
import asyncio
import argparse
import json
from pathlib import Path

import httpx
from hydra.training.generation_reliability import evaluate as reliability
from hydra.training.evaluate_instruction_v2 import evaluate as instruction
from hydra.training.evaluate_corpus import evaluate as coding


async def main(version=4):
    corpus = Path(f"data/hydra-instruction-v{version}")
    results = {}
    for current in (version-1,version):
        name = f"hydra-instruction-v{current}:latest"
        manifest = Path(f"models/hydra-instruction-v{current}/build-manifest.json")
        results[f"v{current}_development"] = await reliability(name,corpus,
            Path(f"docs/evidence/instruction-v{current}-v{version}-development.json"), manifest, "validation")
        if current == version-1:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post("http://127.0.0.1:11434/api/generate",json=dict(model=name,keep_alive=0))
                r.raise_for_status()
    manifest = Path(f"models/hydra-instruction-v{version}/build-manifest.json")
    name=f"hydra-instruction-v{version}:latest"
    results[f"v{version}_calibration"] = await reliability(name,corpus,
        Path(f"docs/evidence/instruction-v{version}-generation-calibration.json"),manifest,"calibration")
    results[f"v{version}_frozen_instruction"] = await instruction(name,
        Path(f"docs/evidence/instruction-v{version}-original-contract.json"),manifest,corpus)
    results[f"v{version}_coding"] = await coding(name,Path("data/hydra-corpus-v1"),
        Path(f"docs/evidence/instruction-v{version}-coding-regression.json"),build_manifest=manifest)
    compact = {k:{field:v[field] for field in ("accuracy","score","correct","total","wilson95","complete") if field in v}
               for k,v in results.items()}
    compact.update(approved=False, independent_test=False, serving_model_changed=False)
    Path(f"docs/evidence/instruction-v{version}-summary.json").write_text(json.dumps(compact,indent=2),encoding="utf-8")
    print(json.dumps(compact,indent=2))


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--version",type=int,choices=[4,5],default=4)
    args=parser.parse_args()
    asyncio.run(main(args.version))
