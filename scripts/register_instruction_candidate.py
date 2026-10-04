# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Import a completed candidate under a new alias without replacing deployed models."""
import argparse
import json
import os
import subprocess
from pathlib import Path

from hydra.training.evaluate_corpus import candidate_hash


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", choices=["2", "3", "4", "5", "6", "7", "8"], required=True)
    args = parser.parse_args()
    name = f"hydra-instruction-v{args.version}"
    root = Path("models") / name
    digest = candidate_hash(root / "build-manifest.json")
    modelfile = Path("runtime") / f"{name}.Modelfile"
    modelfile.write_text(f'FROM "{(root / "HYDRA.gguf").resolve()}"\n'
                        'PARAMETER num_ctx 2048\nPARAMETER temperature 0\nPARAMETER num_gpu 99\n', encoding="utf-8")
    env = {**os.environ, "OLLAMA_HOST": "http://127.0.0.1:11434"}
    with (Path("runtime") / f"{name}-import.log").open("w", encoding="utf-8") as log:
        subprocess.run(["ollama", "create", name, "-f", str(modelfile)], env=env,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    print(json.dumps({"model": name, "artifact_sha256": digest, "approved": False}))
