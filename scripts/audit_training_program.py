# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Audit completeness against the agreed program; pilot integrity is not readiness."""
import argparse
import json
from collections import Counter
from pathlib import Path
from hydra.training.program import validate_corpus


def audit(root, specification):
    integrity = validate_corpus(root)
    families, languages, groups = Counter(), Counter(), {}
    missing, overlaps, pending_reviews = [], [], 0
    mapping = {"train.jsonl": "train", "validation.jsonl": "development",
               "calibration.jsonl": "calibration", "test.jsonl": "independent_test"}
    required = ["family", "scenario_group", "language", "origin", "source_ref",
                "license", "review_status"]
    for filename, split in mapping.items():
        rows = [json.loads(line) for line in (root / filename).read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in rows:
            absent = [key for key in required if not row.get(key)]
            if absent:
                missing.append({"id": row["id"], "fields": absent})
            if row.get("review_status") != "approved":
                pending_reviews += 1
            group = row.get("scenario_group")
            if group and group in groups and groups[group] != split:
                overlaps.append(group)
            if group:
                groups[group] = split
            if split == "train":
                families[row.get("family", "undeclared")] += 1
                languages[row.get("language", "undeclared")] += 1
    quotas = {name: max(0, target - families[name]) for name, target in specification["corpus"]["train_family_targets"].items()}
    split_deficits = {split: max(0, specification["corpus"]["split_targets"][split] - integrity["counts"][filename])
                      for filename, split in mapping.items()}
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    ready = not missing and not overlaps and not pending_reviews and not any(quotas.values()) and not any(split_deficits.values())
    ready = ready and manifest.get("human_reviewed") is True and manifest.get("independent_test") is True
    return {"integrity": integrity, "family_counts": dict(families), "language_counts": dict(languages),
            "missing_metadata_count": len(missing), "missing_metadata_sample": missing[:10],
            "pending_row_reviews": pending_reviews,
            "group_overlap": sorted(set(overlaps)), "family_deficits": quotas, "split_deficits": split_deficits,
            "complete_corpus_ready": bool(ready), "approved": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--specification", type=Path, default=Path("config/training/hydra-training-program-v1.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.corpus, json.loads(args.specification.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"complete_corpus_ready": result["complete_corpus_ready"],
                      "missing_metadata_count": result["missing_metadata_count"]}))
