# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Preserve v8 regression/replay and append the explicitly synthetic web pilot."""
import json
import argparse
from pathlib import Path
from hydra.training.verified_corpus import sha256
from hydra.training.program import validate_corpus


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", type=Path, default=Path("data/hydra-web-grounding-v1-utf8"))
    parser.add_argument("--corpus", type=Path, default=Path("data/hydra-program-v1-clean-pilot"))
    parser.add_argument("--recipe", type=Path, default=Path("config/recipes/hydra-program-v1-clean-pilot.json"))
    parser.add_argument("--model-output", default="models/hydra-program-v1-clean-pilot")
    parser.add_argument("--steps", type=int, default=100)
    args = parser.parse_args()
    if args.recipe.exists() or Path(args.model_output).exists() or args.steps < 1:
        raise ValueError("fresh recipe/output and positive steps required")
    parent = Path("data/hydra-instruction-v8")
    web = args.web
    root = args.corpus
    root.mkdir(exist_ok=False)
    files = {}
    for name in ("train.jsonl", "validation.jsonl", "calibration.jsonl", "test.jsonl"):
        text = (parent / name).read_text(encoding="utf-8")
        if name != "test.jsonl":
            extra = []
            for line in (web / name).read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                row["id"] = "web-pilot-" + row["id"]
                extra.append(json.dumps(row, ensure_ascii=False))
            text = text.rstrip() + "\n" + "\n".join(extra) + "\n"
        path = root / name
        path.write_text(text, encoding="utf-8")
        files[name] = {"examples": len(text.splitlines()), "sha256": sha256(path)}
    manifest = {"version": "program-v1-pilot", "parent_manifest_sha256": sha256(parent / "manifest.json"),
                "files": files, "approved": False, "human_reviewed": False,
                "status": "synthetic_pilot_not_complete_corpus",
                "independent_test": False, "known_test_role": "regression",
                "source_manifest_sha256": sha256(web / "manifest.json"),
                "limitations": "Only four synthetic web families; semantic patterns repeat across splits"}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    report = validate_corpus(root)
    recipe = json.loads(Path("config/recipes/hydra-instruction-v9-seven-high.json").read_text())
    recipe.update(corpus=str(root), output=args.model_output, max_steps=args.steps,
                  training_program=True,
                  warmup_ratio=.03, max_grad_norm=1.0, lr_scheduler_type="linear", eval_batch_size=1)
    args.recipe.write_text(json.dumps(recipe, indent=2), encoding="utf-8")
    Path("docs/evidence/training-program-clean-pilot-corpus.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
