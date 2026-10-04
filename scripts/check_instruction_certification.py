# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Report eligibility; never deploy, promote or rewrite a model manifest."""
import argparse
import json
from pathlib import Path

from hydra.training.evaluate_corpus import candidate_hash
from hydra.training.generation_reliability import wilson
from hydra.training.verified_corpus import sha256
from hydra.training.evidence_io import write_json


def check(root=Path("."), evidence=Path("docs/evidence"), soak_path=Path("docs/evidence/instruction-v5-soak-15m.json"), version=5):
    if version not in (5,6,7):
        raise ValueError("unsupported candidate")
    digest=candidate_hash(root/f"models/hydra-instruction-v{version}/build-manifest.json")
    def read(relative):
        path=root/relative
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    quality=read(evidence/f"instruction-v{version}-summary.json")
    soak=read(soak_path)
    external=read(evidence/f"external-evaluation-v{version}.json")
    reviews=read(f"runtime/external-evaluation-v{version}-reviews.json")
    manifest=read("data/external-evaluation-v2/manifest.json")
    excluded={i for group in manifest.get("duplicate_groups",[]) for i in group[1:]}
    rows=read("data/external-evaluation-v2/cases.json") or []
    answers={str(c["id"]):c for c in external.get("cases",[])}
    valid={}
    for row in rows:
        key=str(row["id"])
        rating=reviews.get("cases",{}).get(key,{})
        answer=answers.get(key,{})
        if row["id"] not in excluded and rating.get("decision") in {"correct","incorrect","ambiguous"} and str(rating.get("reviewer","")).strip() and rating.get("artifact_sha256")==digest and "output" in answer and not answer.get("error"):
            valid[key]=rating
    human_complete=bool(len(valid)==manifest.get("unique_cases") and len(valid)>=100)
    human_correct=sum(c["decision"]=="correct" for c in valid.values())
    total=manifest.get("unique_cases",0)
    interval=wilson(human_correct,total) if total else [0,1]
    gates={
        "fresh_process_complete":read(evidence/"status.json").get("complete") is True if evidence!=Path("docs/evidence") else True,
        "fresh_software_checks_passed":read(evidence/"software-checks.json").get("passed") is True if evidence!=Path("docs/evidence") else True,
        "development_above_90":quality.get(f"v{version}_development",{}).get("accuracy",0)>.90,
        "calibration_above_90":quality.get(f"v{version}_calibration",{}).get("accuracy",0)>.90,
        "frozen_instructions_above_90":quality.get(f"v{version}_frozen_instruction",{}).get("accuracy",0)>.90,
        "coding_regression_retained":quality.get(f"v{version}_coding",{}).get("score",0)==1,
        "soak_15m_passed":soak.get("complete") is True and soak.get("soak_gate_passed") is True and soak.get("artifact_sha256")==digest,
        "external_inference_complete":external.get("complete") is True and external.get("artifact_sha256")==digest,
        "human_review_complete":human_complete,
        "human_authorship_attested":reviews.get("human_authorship_attested") is True,
        "human_accuracy_above_90":bool(total and human_correct/total>.90 and interval[0]>=.90),
        "reviews_bound_to_candidate":reviews.get("artifact_sha256")==digest and reviews.get("dataset_sha256")==manifest.get("cases_sha256"),
    }
    if manifest:
        gates["external_test_unchanged"]=sha256(root/"data/external-evaluation-v2/cases.json")==manifest.get("cases_sha256")
    for label,filename in (("development",f"instruction-v{version}-v{version}-development.json"),("calibration",f"instruction-v{version}-generation-calibration.json"),
                           ("frozen_instruction",f"instruction-v{version}-original-contract.json"),("coding",f"instruction-v{version}-coding-regression.json")):
        report=read(evidence/filename)
        bound=report.get("artifact_sha256") or report.get("identity",{}).get("artifact_sha256") or report.get("model_identity",{}).get("artifact_sha256")
        gates[label+"_bound_to_candidate"]=bound==digest
    report=dict(artifact_sha256=digest,gates=gates,eligible_for_manual_promotion=all(gates.values()),approved=False,
                evidence_directory=str(evidence),human_reviewed=len(valid),human_unique_cases=total,human_wilson95=interval,
                pending=[name for name,passed in gates.items() if not passed],
                scope="evidence gates for bounded evaluated tasks; no claim of universal certification")
    write_json(root/evidence/f"instruction-v{version}-certification-gates.json",report)
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--evidence",type=Path,default=Path("docs/evidence"))
    parser.add_argument("--soak",type=Path,default=Path("docs/evidence/instruction-v5-soak-15m.json"))
    parser.add_argument("--version",type=int,choices=[5,6,7],default=5)
    args=parser.parse_args()
    print(json.dumps(check(evidence=args.evidence,soak_path=args.soak,version=args.version),indent=2))
