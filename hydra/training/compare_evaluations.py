# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Compare completed holdouts without turning a pilot score into release approval."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hydra.training.verified_corpus import sha256


def compare(base: dict, candidate: dict) -> dict:
    for report in (base, candidate):
        if report.get("status") != "EVALUATED" or report.get("subset") is not False:
            raise ValueError("comparison requires two completed full holdouts")
        if not report.get("dataset_sha256"):
            raise ValueError("missing dataset identity")
        identity = report.get("model_identity", {})
        if not identity.get("digest") or not identity.get("artifact_sha256"):
            raise ValueError("missing served model identity")
        cases = report.get("cases", [])
        if (not cases or len({c["id"] for c in cases}) != len(cases)
                or any(type(c.get("passed")) is not bool for c in cases)):
            raise ValueError("invalid or duplicate evaluation cases")
    if base["dataset_sha256"] != candidate["dataset_sha256"]:
        raise ValueError("holdout datasets differ")
    before = {c["id"]: c for c in base["cases"]}
    after = {c["id"]: c for c in candidate["cases"]}
    if before.keys() != after.keys():
        raise ValueError("holdout case sets differ")
    base_score = sum(c["passed"] for c in before.values()) / len(before)
    candidate_score = sum(c["passed"] for c in after.values()) / len(after)
    return {"status": "COMPARED_PILOT", "approved": False,
            "dataset_sha256": base["dataset_sha256"], "cases": len(before),
            "base_identity": base["model_identity"], "candidate_identity": candidate["model_identity"],
            "base_score": base_score, "candidate_score": candidate_score,
            "score_delta": candidate_score - base_score,
            "regressions": [key for key in before if before[key]["passed"] and not after[key]["passed"]],
            "improvements": [key for key in before if not before[key]["passed"] and after[key]["passed"]],
            "limitations": "Pilot holdout only. Does not establish general quality, latency or release readiness."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(json.loads(args.base.read_text(encoding="utf-8")),
                     json.loads(args.candidate.read_text(encoding="utf-8")))
    result["report_hashes"] = {"base": sha256(args.base), "candidate": sha256(args.candidate)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
