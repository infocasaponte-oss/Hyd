# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Hash-bound local audit of 1.5B weights, curriculum and previous evaluation evidence."""
import argparse
import json
from pathlib import Path

from hydra.model_factory.gguf import read_gguf
from hydra.training.evaluate_corpus import candidate_hash
from hydra.training.instruction_corpus_v4 import normalized
from hydra.training.verified_corpus import sha256


def audit(root, output):
    manifest_path = root/"build-manifest.json"
    build = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = candidate_hash(manifest_path)
    info = read_gguf(root/"HYDRA.gguf")
    corpus = Path(build["inputs"]["recipe"]["corpus"])
    manifest = json.loads((corpus/"manifest.json").read_text(encoding="utf-8"))
    prompts, count, files = set(), 0, {}
    for name, entry in manifest["files"].items():
        path = corpus/name
        if sha256(path) != entry["sha256"]:
            raise ValueError("corpus hash changed")
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if len(rows) != entry["examples"]:
            raise ValueError("corpus count changed")
        for row in rows:
            prompt = normalized(row["messages"][1]["content"])
            if prompt in prompts:
                raise ValueError("duplicate or leaked prompt")
            prompts.add(prompt)
            count += 1
        files[name] = dict(examples=len(rows), sha256=entry["sha256"])
    verified_stages = []
    for stage, artifacts in build["stages"].items():
        for file, expected in artifacts.items():
            if sha256(Path(file)) != expected:
                raise ValueError(f"build artifact changed: {file}")
        verified_stages.append(stage)
    config = json.loads((root/"merged/config.json").read_text())
    report = dict(model=str(root), artifact_sha256=digest, size_bytes=(root/"HYDRA.gguf").stat().st_size,
                  architecture=info.architecture, parameters=info.parameters, quantization=info.file_type,
                  text_only="vision_config" not in config, trained_on_gpu=json.loads((root/"adapter/metrics.json").read_text())["device"] == "cuda",
                  files=files, unique_prompts=count, verified_stages=verified_stages,
                  approved=False, limitations="Hash integrity and synthetic regressions do not certify broad accuracy or autonomous authority.")
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--model",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(audit(a.model,a.output),indent=2))
