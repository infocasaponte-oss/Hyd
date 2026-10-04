# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Export existing local Ollama weights as a baseline, preserving provenance."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path

import httpx

from hydra.model_factory.gguf import read_gguf
from hydra.training.verified_corpus import sha256


def export(model: str, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    response = httpx.post("http://127.0.0.1:11434/api/show", json={"model":model}, timeout=30)
    response.raise_for_status()
    details = response.json()
    match = re.search(r"^FROM\s+(.+)$", details["modelfile"], re.MULTILINE)
    if not match:
        raise ValueError("Ollama did not return a local weights path")
    source = Path(match.group(1).strip().strip('"')).resolve()
    info = read_gguf(source)
    if not info.tensors:
        raise ValueError("source has no tensors")
    source_hash = sha256(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(".partial")
    if partial.exists():
        raise FileExistsError(partial)
    with source.open("rb") as src, partial.open("xb") as dst:
        shutil.copyfileobj(src,dst,8*1024*1024)
        dst.flush()
        os.fsync(dst.fileno())
    if sha256(partial) != source_hash:
        raise ValueError("export checksum mismatch")
    partial.rename(output)
    manifest = {"status":"BASELINE_NOT_HYDRA_TRAINED", "approved":False,
                "source_model":model,"source_path":str(source),"sha256":source_hash,
                "artifact":str(output.resolve()),"size_bytes":output.stat().st_size,
                "architecture":info.architecture,"quantization":info.file_type}
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    output.with_suffix(".LICENSE.txt").write_text(details.get("license", "License not returned by Ollama"),encoding="utf-8")
    return manifest


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model",default="qwen2.5-coder:7b")
    p.add_argument("--output",type=Path,default=Path("models/HYDRA-baseline.gguf"))
    args = p.parse_args()
    print(json.dumps(export(args.model,args.output),indent=2))
