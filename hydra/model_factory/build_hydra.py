# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Train, merge and build a traceable HYDRA.gguf candidate. No automatic promotion.

python -m hydra.model_factory.build_hydra --recipe config/recipes/hydra-pilot.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from hydra.model_factory.gguf import read_gguf
from hydra.training.verified_corpus import sha256
from hydra.training.corpus_integrity import validate_parent_replay


def checked(cmd: list[str], log: Path) -> None:
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(cmd, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}); inspect {log}")


def validate_inputs(recipe: dict) -> dict:
    base, corpus = Path(recipe["base_model"]), Path(recipe["corpus"])
    required = [base/"model.safetensors", base/"config.json", base/"tokenizer_config.json",
                corpus/"manifest.json", Path(recipe["llamacpp"])/"convert_hf_to_gguf.py", Path(recipe["quantizer"])]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise ValueError("missing build inputs: " + ", ".join(missing))
    base_hash = sha256(base/"model.safetensors")
    if base_hash != recipe["base_sha256"]:
        raise ValueError("base weights do not match pinned source SHA256")
    # Opening a partial download must fail before training starts.
    from safetensors import safe_open
    with safe_open(str(base/"model.safetensors"), framework="pt", device="cpu") as weights:
        if not list(weights.keys()):
            raise ValueError("base has no weights")
    manifest = json.loads((corpus/"manifest.json").read_text(encoding="utf-8"))
    if (corpus / "QUARANTINED.json").exists():
        raise ValueError("corpus is quarantined; use a corrected new dataset and recipe")
    if recipe.get("training_program"):
        from hydra.training.program import validate_corpus
        validate_corpus(corpus)
    validate_parent_replay(corpus,manifest)
    for split in ("train", "validation", "test"):
        filename = f"{split}.jsonl"
        if sha256(corpus/filename) != manifest["files"][filename]["sha256"]:
            raise ValueError(f"dataset hash mismatch: {filename}")
    if "calibration.jsonl" in manifest["files"]:
        if sha256(corpus/"calibration.jsonl") != manifest["files"]["calibration.jsonl"]["sha256"]:
            raise ValueError("dataset hash mismatch: calibration.jsonl")
    if recipe.get("resume_from_checkpoint"):
        checkpoint = Path(recipe["resume_from_checkpoint"])
        pinned = recipe.get("resume_checkpoint_sha256", {})
        required_resume = {"adapter_model.safetensors", "optimizer.pt", "scheduler.pt", "rng_state.pth", "trainer_state.json"}
        if not required_resume.issubset(pinned):
            raise ValueError("resume checkpoint must pin adapter, optimizer, scheduler, RNG and trainer state")
        if any(not (checkpoint/name).is_file() or sha256(checkpoint/name) != digest for name,digest in pinned.items()):
            raise ValueError("resume checkpoint changed")
    return {"base_sha256": base_hash, "dataset": manifest,
            "recipe": recipe, "quantizer_sha256": sha256(Path(recipe["quantizer"])),
            "converter_sha256": sha256(Path(recipe["llamacpp"])/"convert_hf_to_gguf.py"),
            "trainer_sha256": sha256(Path(__file__).with_name("train_lora.py"))}


def build(recipe_path: Path) -> Path:
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    evidence = validate_inputs(recipe)
    root = Path(recipe["output"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root/"build-manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old["inputs"] != evidence:
            raise ValueError("build inputs changed; use a new output directory")
        # Resuming: completed stages are re-verified by hash; a previous error no longer applies.
        old.pop("error", None)
        old["status"] = "BUILDING"
    else:
        old = {"inputs": evidence, "stages": {}, "status": "BUILDING", "approved": False}
    def save():
        temp = manifest_path.with_suffix(".tmp")
        temp.write_text(json.dumps(old, indent=2),encoding="utf-8")
        temp.replace(manifest_path)
    save()
    def stage(name, cmd, artifacts):
        previous = old["stages"].get(name)
        if previous and all(p.is_file() and sha256(p) == previous.get(str(p)) for p in artifacts):
            return
        if previous:
            raise ValueError(f"stage {name} artifacts changed; use a new output directory")
        checked(cmd, root/f"{name}.log")
        if any(not p.is_file() or not p.stat().st_size for p in artifacts):
            raise RuntimeError(f"{name} did not produce required outputs")
        old["stages"][name] = {str(p): sha256(p) for p in artifacts}
        save()
    job = {**recipe, "base_model": str(Path(recipe["base_model"]).resolve()),
           "dataset": str((Path(recipe["corpus"])/"train.jsonl").resolve()),
           "validation": str((Path(recipe["corpus"])/"validation.jsonl").resolve()),
           "output_dir": str(root/"adapter")}
    (root/"job.json").write_text(json.dumps(job,indent=2),encoding="utf-8")
    try:
        stage("train", [sys.executable,"-m","hydra.model_factory.train_lora",str(root/"job.json")],
              [root/"adapter/adapter_model.safetensors",root/"adapter/adapter_config.json",root/"adapter/metrics.json"])
        stage("merge", [sys.executable,"-m","hydra.model_factory.train_lora","--merge",job["base_model"],
                        str(root/"adapter"),str(root/"merged")],
              [root/"merged/model.safetensors",root/"merged/config.json",root/"merged/tokenizer_config.json"])
        stage("convert", [sys.executable,str(Path(recipe["llamacpp"])/"convert_hf_to_gguf.py"),
                          str(root/"merged"),"--outfile",str(root/"HYDRA-f16.gguf"),"--outtype","f16"],
              [root/"HYDRA-f16.gguf"])
        target = root/"HYDRA.gguf"
        quantization = recipe.get("quantization", "Q4_K_M")
        if quantization not in {"Q4_K_M", "Q5_K_M", "Q8_0"}:
            raise ValueError("unsupported candidate quantization")
        # Windows CreateProcess cannot launch a relative "a/b/c.exe" path; resolve it first.
        quantizer = str(Path(recipe["quantizer"]).resolve())
        stage("quantize", [quantizer,str(root/"HYDRA-f16.gguf"),str(target),quantization], [target])
        info = read_gguf(target)
        if not info.tensors or info.file_type != quantization:
            raise ValueError("invalid or unexpected GGUF output")
        old.update(status="CANDIDATE_REQUIRES_EVALUATION", approved=False,
                   artifact=str(target), sha256=sha256(target), architecture=info.architecture)
        save()
        (root/"SHA256SUMS").write_text(f"{old['sha256']}  HYDRA.gguf\n",encoding="utf-8")
        return target
    except BaseException as exc:
        old.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
        save()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe",type=Path,default=Path("config/recipes/hydra-pilot.json"))
    parser.add_argument("--check",action="store_true")
    args = parser.parse_args()
    if args.check:
        print(json.dumps(validate_inputs(json.loads(args.recipe.read_text(encoding="utf-8"))),indent=2))
    else:
        print(build(args.recipe))
