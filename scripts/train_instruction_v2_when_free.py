# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Wait for free GPU memory, then run the pinned build without stopping other services."""
import json
import subprocess
import time
import argparse
from pathlib import Path

from hydra.model_factory.build_hydra import build


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", type=Path, default=Path("config/recipes/hydra-instruction-v2.json"))
    args = parser.parse_args()
    status = Path("runtime") / f"{args.recipe.stem}-status.json"
    start = time.monotonic()
    while True:
        free = int(subprocess.check_output(["nvidia-smi", "--query-gpu=memory.free",
                   "--format=csv,noheader,nounits"], text=True).splitlines()[0].strip())
        status.write_text(json.dumps({"stage": "WAITING_GPU", "free_mib": free,
                                      "required_free_mib": 5500}), encoding="utf-8")
        if free >= 5500:
            break
        if time.monotonic() - start > 600:
            raise RuntimeError("GPU still occupied; training not started")
        time.sleep(2)
    status.write_text(json.dumps({"stage": "BUILDING", "approved": False}), encoding="utf-8")
    try:
        artifact = build(args.recipe)
        status.write_text(json.dumps({"stage": "CANDIDATE_REQUIRES_EVALUATION",
                                      "artifact": str(artifact), "approved": False}), encoding="utf-8")
        print(artifact, flush=True)
    except BaseException as exc:
        status.write_text(json.dumps({"stage": "FAILED", "error": str(exc), "approved": False}), encoding="utf-8")
        raise
