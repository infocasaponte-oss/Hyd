# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Serve an explicitly selected completed local Kev experiment on CUDA."""
import argparse
import os
import runpy
import sys
from pathlib import Path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8009)
    parser.add_argument("--source-root", type=Path, default=Path("runtime/kev-hydra"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.source_root:
        source = args.source_root.resolve()
        source.relative_to(root / "runtime")
        if not (source / "kev/serve.py").is_file():
            raise ValueError("Missing Kev source")
        if source == root / "runtime/kev-hydra":
            import json
            from scripts.prepare_kev_reliability_fork import validate
            validate(source, json.loads((root / "patches/kev/manifest.json").read_text(encoding="utf-8")))
        sys.path.insert(0, str(source))
    checkpoint = args.run.resolve()
    checkpoint.relative_to(root / "models")
    for name in ("head.pt", "adapter_config.json", "adapter_model.safetensors"):
        if not (checkpoint / name).is_file():
            raise ValueError(f"Incomplete candidate: {name}")
    os.environ["HF_HOME"] = str(root / "runtime/kev-cache")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["KEV_DTYPE"] = "bf16"
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("Candidate serving requires CUDA")
    sys.argv = ["kev.serve", "--run", str(checkpoint), "--host", "127.0.0.1", "--port", str(args.port)]
    runpy.run_module("kev.serve", run_name="__main__")
