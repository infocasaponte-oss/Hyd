# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Export aggregate evidence only from completed, paired local development runs."""
import argparse
import json
from pathlib import Path

import numpy as np

from hydra.training.decision_candidates import file_sha
from hydra.training.decision_compare import paired_summary
from hydra.training.decision_metrics import metrics
from hydra.training.evidence_io import write_json


def collect(root):
    names = {
        "frozen_A": "comparison-frozen-kev-r1.json",
        "tuned_A": "comparison-tuned-kev-r1.json",
        "hash_A": "comparison-hash-kev-r1.json",
        "frozen_B": "comparison-person-juan-kev-r1.json",
        "frozen_C": "comparison-person-belen-kev-r1.json",
        "balanced_A": "comparison-balanced-kev-r1.json",
        "balanced_B": "comparison-balanced-person-juan-kev-r1.json",
        "balanced_C": "comparison-balanced-person-belen-kev-r1.json",
    }
    records, combined_hyd, combined_kev = {}, [], []
    balanced_hyd, balanced_kev = [], []
    reference = None
    cohort_bindings = {}
    for label, filename in names.items():
        path = root / filename
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != "hyd-kev-paired/1" or data.get("complete") is not True:
            raise ValueError("completed comparison required")
        binding = (data["kev_checkpoint_files"], data["kev_calibration_sha256"])
        if reference is None:
            reference = binding
        if binding != reference:
            raise ValueError("different Kev checkpoint or calibrator")
        cohort = label.rsplit("_", 1)[1]
        baseline = {r["id"]: {k: r[k] for k in
                    ("text_sha256", "group_id", "expected", "selected", "probabilities")}
                    for r in data["kev_rows"]}
        cohort_binding = (data["test_sha256"], baseline)
        if cohort in cohort_bindings and cohort_bindings[cohort] != cohort_binding:
            raise ValueError("different test or Kev predictions within a cohort")
        cohort_bindings[cohort] = cohort_binding
        summary = paired_summary(data["hyd_rows"], data["kev_rows"])
        diagnostics = {}
        for model in ("hyd", "kev"):
            rows = data[model + "_rows"]
            latencies = [r["elapsed_ms"] for r in rows]
            diagnostics[model] = {"selective_by_max_probability": {str(t): metrics(rows, t) for t in (.9, .95, .99)},
                "latency_ms_median": float(np.median(latencies)), "latency_ms_p95": float(np.quantile(latencies, .95)),
                "errors_by_class": {label: {
                    "false_positive": sum(r["selected"] == label and r["expected"] != label for r in rows),
                    "false_negative": sum(r["selected"] != label and r["expected"] == label for r in rows)}
                    for label in summary[model]["per_class"]}}
        records[label] = {"evidence_sha256": file_sha(path), "summary": summary, "diagnostics": diagnostics}
        if label.startswith("frozen_"):
            combined_hyd.extend(data["hyd_rows"])
            combined_kev.extend(data["kev_rows"])
        if label.startswith("balanced_"):
            balanced_hyd.extend(data["hyd_rows"])
            balanced_kev.extend(data["kev_rows"])
    return {"format": "hyd-kev-development-aggregate/1", "complete": True,
        "independent_test": False, "authority": False, "public_contains_raw_questions": False,
        "folds": records, "frozen_lopo": paired_summary(combined_hyd, combined_kev),
        "balanced_lopo": paired_summary(balanced_hyd, balanced_kev),
        "limitation": "Three previously inspected human cohorts; candidate comparisons and family intervals are development evidence, not certification. Latencies measure Hyd inference versus Kev HTTP inference plus identity verification; cached baseline latencies are reused."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("new output required")
    report = collect(args.root)
    write_json(args.out, report)
    print(json.dumps({"rows": report["frozen_lopo"]["paired_n"],
        "hyd_frozen": report["frozen_lopo"]["hyd"]["accuracy"],
        "hyd_balanced": report["balanced_lopo"]["hyd"]["accuracy"],
        "kev": report["frozen_lopo"]["kev"]["accuracy"]}, indent=2))


if __name__ == "__main__":
    main()
