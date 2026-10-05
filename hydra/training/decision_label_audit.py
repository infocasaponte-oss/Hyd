# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Prepare a private, blind human review bundle without changing corpus labels."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from hydra.router.decision_contract import CRITERIA
from hydra.training.decision_active_learning import read_rows, text_label
from hydra.training.decision_candidates import file_sha
from hydra.training.decision_compare import paired_summary
from hydra.training.evidence_io import write_json


def prepare(corpus: Path, comparisons: list[Path], out: Path, labels=("privacy", "abstain")):
    if out.exists():
        raise FileExistsError("new private review directory required")
    if len(set(labels)) < 2 or not set(labels) <= set(CRITERIA):
        raise ValueError("at least two valid routing labels required")
    originals = read_rows(corpus)
    by_id = {r["id"]: r for r in originals}
    if len(by_id) != len(originals):
        raise ValueError("unique original IDs required")
    selected, seen, counts = {}, set(), Counter()
    for path in comparisons:
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if evidence.get("format") != "hyd-kev-paired/1" or evidence.get("complete") is not True:
            raise ValueError("completed paired development evidence required")
        paired_summary(evidence["hyd_rows"], evidence["kev_rows"])
        kev = {r["id"]: r for r in evidence["kev_rows"]}
        for row in evidence["hyd_rows"]:
            if row["id"] in seen:
                raise ValueError("each question must appear in one comparison only")
            seen.add(row["id"])
            original = by_id[row["id"]]
            text, expected = text_label(original)
            digest = hashlib.sha256(text.encode()).hexdigest()
            if digest != row["text_sha256"] or digest != original["text_sha256"] or expected != row["expected"]:
                raise ValueError("comparison does not match original corpus")
            if expected not in labels:
                continue
            predictions = {"hyd": row["selected"], "kev": kev[row["id"]]["selected"]}
            cross = False
            for model, prediction in predictions.items():
                if prediction in labels and prediction != expected:
                    counts[f"{model}:{expected}->{prediction}"] += 1
                    cross = True
            selected[row["id"]] = (original, predictions, cross)
    # Include ALL original rows in the two classes, not only AI disagreements.
    required = {r["id"] for r in originals if text_label(r)[1] in labels}
    if set(selected) != required:
        raise ValueError("comparisons must cover all questions in the reviewed classes")
    ordered = sorted(selected.values(), key=lambda item: (not item[2], item[0]["id"]))
    blind, bindings = [], []
    for original, predictions, cross in ordered:
        text, expected = text_label(original)
        blind.append({"id": original["id"], "text": text, "text_sha256": original["text_sha256"],
                      "human_label": None, "reviewer": None, "notes": None, "confirmed": False,
                      "training_allowed": False})
        bindings.append({"id": original["id"], "previous_expected": expected,
                         "predictions_for_auditor_only": predictions, "cross_route_disagreement": cross})
    out.mkdir(parents=True)
    for name, rows in (("review-blind.jsonl", blind), ("auditor-bindings.jsonl", bindings)):
        (out / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    manifest = {"format": "hyd-label-review/1", "authority": False, "training_allowed": False,
                "source_sha256": file_sha(corpus), "comparison_sha256": [file_sha(p) for p in comparisons],
                "labels": list(labels), "total_original_rows": len(originals), "review_rows": len(blind),
                "priority_rows": sum(item[2] for item in ordered), "disagreements": dict(counts),
                "originals_modified": False, "contains_private_questions": True,
                "files": {n: file_sha(out / n) for n in ("review-blind.jsonl", "auditor-bindings.jsonl")},
                "instructions": "Review blind text before consulting auditor bindings. Predictions are not truth. Preserve original and confirmation events; issue a new corpus version after human adjudication. This inspected set is not a new blind test."}
    write_json(out / "MANIFEST.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.corpus, args.comparison, args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
