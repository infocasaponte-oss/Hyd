# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Replay the clean program pilot and append the source-grounded corpus; write a LoRA recipe.

Prepares inputs only; training runs with
``python -m hydra.model_factory.build_hydra --recipe config/recipes/hydra-program-v2-grounded.json``.
"""
import argparse
import json
import math
from pathlib import Path

from hydra.training.program import validate_corpus
from hydra.training.verified_corpus import sha256

SPLITS = ("train.jsonl", "validation.jsonl", "calibration.jsonl", "test.jsonl")


def check_lengths(corpus: Path, tokenizer_dir: Path, max_length: int) -> dict:
    """Encode every new row exactly as train_lora does, so no run dies mid-training."""
    from transformers import AutoTokenizer  # type: ignore
    from hydra.model_factory.train_lora import encode_response

    tok = AutoTokenizer.from_pretrained(str(tokenizer_dir))
    longest = 0
    for name in SPLITS:
        for line in (corpus / name).read_text(encoding="utf-8").splitlines():
            encoded = encode_response(tok, json.loads(line)["messages"], max_length)
            longest = max(longest, len(encoded["input_ids"]))
    return {"max_tokens": longest, "limit": max_length}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", type=Path, default=Path("data/hydra-program-v1-clean-pilot"))
    parser.add_argument("--grounded", type=Path, default=Path("data/hydra-grounded-v1"))
    parser.add_argument("--corpus", type=Path, default=Path("data/hydra-program-v2-grounded"))
    parser.add_argument("--base-recipe", type=Path, default=Path("config/recipes/hydra-program-v1-clean-pilot.json"))
    parser.add_argument("--recipe", type=Path, default=Path("config/recipes/hydra-program-v2-grounded.json"))
    parser.add_argument("--model-output", default="models/hydra-program-v2-grounded")
    parser.add_argument("--epochs", type=float, default=1.0, help="sizes max_steps over the combined train split")
    parser.add_argument("--skip-length-check", action="store_true")
    args = parser.parse_args()
    if args.recipe.exists() or Path(args.model_output).exists() or args.epochs <= 0:
        raise ValueError("fresh recipe/output and positive epochs required")
    if (args.grounded / "QUARANTINED.json").exists():
        raise ValueError("grounded corpus is quarantined")
    validate_corpus(args.parent)
    validate_corpus(args.grounded)
    grounded_manifest = json.loads((args.grounded / "manifest.json").read_text(encoding="utf-8"))
    args.corpus.mkdir(exist_ok=False)
    files = {}
    for name in SPLITS:
        parent_text = (args.parent / name).read_text(encoding="utf-8")
        new_text = (args.grounded / name).read_text(encoding="utf-8")
        text = parent_text.rstrip("\n") + "\n" + new_text
        path = args.corpus / name
        path.write_text(text, encoding="utf-8")
        files[name] = {"examples": len(text.splitlines()), "sha256": sha256(path),
                       "replayed": len(parent_text.splitlines()), "grounded": len(new_text.splitlines())}
    manifest = {"version": "program-v2-grounded", "parent_manifest_sha256": sha256(args.parent / "manifest.json"),
                "source_manifest_sha256": sha256(args.grounded / "manifest.json"),
                "source_inputs": grounded_manifest["inputs"], "files": files, "approved": False,
                "human_reviewed": False, "independent_test": False, "known_test_role": "regression",
                "status": "synthetic_and_extractive_pilot_not_complete_corpus",
                "limitations": ("Parent replay plus extractive BOE/Python grounding; test mixes the frozen parent "
                                "regression set with document-disjoint grounded cases. Not human reviewed.")}
    (args.corpus / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    report = validate_corpus(args.corpus)

    recipe = json.loads(args.base_recipe.read_text(encoding="utf-8"))
    if not args.skip_length_check:
        report["length_check"] = check_lengths(args.corpus, Path(recipe["base_model"]), recipe["max_seq_length"])
    steps = math.ceil(files["train.jsonl"]["examples"] / (recipe["batch_size"] * recipe["gradient_accumulation"]) * args.epochs)
    recipe.update(corpus=str(args.corpus), output=args.model_output, max_steps=steps, training_program=True)
    args.recipe.write_text(json.dumps(recipe, indent=2) + "\n", encoding="utf-8")
    report.update(recipe=str(args.recipe), max_steps=steps, epochs=args.epochs,
                  corpus_manifest_sha256=sha256(args.corpus / "manifest.json"))
    # docs/evidence/training-<recipe name>-corpus.json, so each run keeps its own evidence.
    evidence = Path("docs/evidence") / f"training-{args.recipe.stem.removeprefix('hydra-')}-corpus.json"
    if evidence.exists():
        raise FileExistsError(f"{evidence} already records another run")
    evidence.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
