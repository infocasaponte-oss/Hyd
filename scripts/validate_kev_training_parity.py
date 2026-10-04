# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Tiny deterministic GPU check: the reliability patch must not alter SFT math."""
import json
import subprocess
from pathlib import Path
import torch
from safetensors.torch import load_file


if __name__ == "__main__":
    data = Path("runtime/kev-parity-train-v1.jsonl")
    data.write_text("\n".join(Path("data/kev-hydra-v2/train.jsonl").read_text(encoding="utf-8").splitlines()[:4])+"\n", encoding="utf-8")
    outputs = []
    for label, source in (("original", "runtime/kev"), ("patched", "runtime/kev-hydra")):
        output = Path("models") / f"kev-training-parity-{label}-v1"
        if output.exists():
            raise FileExistsError(output)
        command = ["runtime/kev-env/Scripts/python.exe", "-u", "-m", "scripts.train_kev_windows",
                   "--source-root", source, "--data", str(data), "--out", str(output),
                   "--base", "Qwen/Qwen3.5-0.8B-Base", "--base_revision", "dc7cdfe2ee4154fa7e30f5b51ca41bfa40174e68",
                   "--init_from", "jaredpalmer/kev-0.8b@9a45d25eb2ab761841196625383fa1dff0e56c1e",
                   "--lora", "16", "--head_dim", "256", "--device", "cuda", "--dtype", "bf16", "--weights_dtype", "bf16",
                   "--epochs", "1", "--batch", "1", "--accum", "1", "--checkpointing", "1", "--lr", "2e-5",
                   "--p_none", "0", "--p_none_distract", "0", "--p_distract", "0", "--p_none_pair", "0", "--seed", "42"]
        with (Path("runtime") / f"kev-parity-{label}.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        outputs.append(output)
    differences = []
    for kind in ("adapter", "head"):
        states = [load_file(str(p / "adapter_model.safetensors")) if kind == "adapter"
                  else torch.load(p / "head.pt", map_location="cpu", weights_only=False)["head"] for p in outputs]
        if set(states[0]) != set(states[1]):
            raise ValueError("Parameter keys changed")
        differences.extend(float((states[0][k]-states[1][k]).abs().max()) for k in states[0])
    result = {"scope": "four admitted development requests, seed 42, CUDA/bf16, four optimizer steps",
              "tensors": len(differences), "max_abs_difference": max(differences), "bit_identical": max(differences) == 0,
              "approved": False}
    Path("docs/evidence/kev-training-patch-parity.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    if not result["bit_identical"]:
        raise RuntimeError("Training weights changed")
