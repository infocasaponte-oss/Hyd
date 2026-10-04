# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Import the audited package into a separate, reproducible v8 candidate."""
import argparse
import json
import shutil
from pathlib import Path

from hydra.training.finetuning_v8 import prepare
from hydra.training.verified_corpus import sha256
from hydra.training.evidence_io import write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("C:/Users/mejil/Downloads/files"))
    args = parser.parse_args()
    corpus = Path("data/hydra-instruction-v8")
    manifest = prepare(args.source, corpus)
    snapshot = Path("workspace/finetuning-v8/originals")
    snapshot.mkdir(parents=True, exist_ok=False)
    for p in args.source.iterdir():
        if p.is_file():
            shutil.copy2(p, snapshot/p.name)
    base = Path("models/hydra-instruction-v7/merged")
    recipe = json.loads(Path("config/recipes/hydra-instruction-v7.json").read_text(encoding="utf-8"))
    recipe.update(base_model=str(base), base_repository="local:HYDRA-instruction-v7-merged",
                  base_revision=sha256(base/"model.safetensors"), base_sha256=sha256(base/"model.safetensors"),
                  base_size_bytes=(base/"model.safetensors").stat().st_size,
                  corpus=str(corpus), output="models/hydra-instruction-v8", epochs=2,
                  max_seq_length=768, learning_rate=2e-5, select_best=True,
                  parent_build_manifest_sha256=sha256(Path("models/hydra-instruction-v7/build-manifest.json")))
    write_json(Path("config/recipes/hydra-instruction-v8.json"), recipe)
    print(json.dumps(manifest["new_examples"]))


if __name__ == "__main__":
    main()
