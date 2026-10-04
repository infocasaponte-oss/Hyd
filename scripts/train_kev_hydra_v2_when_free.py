# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Sequential CUDA training of a separate Kev candidate; no deployment or promotion."""
import json
import argparse
import subprocess
import time
from pathlib import Path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("models/kev-hydra-v2-r1"))
    output = parser.parse_args().output
    if output.exists():
        raise FileExistsError("Kev candidate output already exists")
    status = Path("runtime") / f"{output.name}-status.json"
    started = time.monotonic()
    while True:
        free = int(subprocess.check_output(["nvidia-smi", "--query-gpu=memory.free",
                   "--format=csv,noheader,nounits"], text=True).splitlines()[0])
        predecessor = Path("models/hydra-instruction-v3/build-manifest.json")
        ready = predecessor.exists() and json.loads(predecessor.read_text())["status"] == "CANDIDATE_REQUIRES_EVALUATION"
        status.write_text(json.dumps({"stage": "WAITING_GPU_AND_PREDECESSOR", "free_mib": free,
                                      "approved": False}), encoding="utf-8")
        if ready and free >= 5500:
            break
        if time.monotonic()-started > 1200:
            raise RuntimeError("Kev GPU admission timed out; no training started")
        time.sleep(2)
    status.write_text(json.dumps({"stage": "TRAINING", "approved": False}), encoding="utf-8")
    command = ["runtime/kev-env/Scripts/python.exe", "-u", "-m", "scripts.train_kev_windows",
        "--data", "data/kev-hydra-v2/train.jsonl", "--init_from",
        "jaredpalmer/kev-0.8b@9a45d25eb2ab761841196625383fa1dff0e56c1e",
        "--base", "Qwen/Qwen3.5-0.8B-Base", "--base_revision",
        "dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68", "--lora", "16", "--head_dim", "256",
        "--out", str(output), "--device", "cuda", "--dtype", "bf16", "--weights_dtype", "bf16",
        "--epochs", "1", "--batch", "1", "--accum", "4", "--checkpointing", "1", "--lr", "2e-5",
        "--p_none", "0", "--p_none_distract", "0", "--p_distract", "0", "--p_none_pair", "0", "--seed", "42"]
    with (Path("runtime") / f"{output.name}-training.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    status.write_text(json.dumps({"stage": "CANDIDATE_REQUIRES_EVALUATION" if result.returncode == 0 else "FAILED",
        "approved": False, "returncode": result.returncode, "output": str(output), "command": command}), encoding="utf-8")
    if result.returncode:
        raise RuntimeError("Kev training failed; inspect runtime/kev-hydra-v2-training.log")
