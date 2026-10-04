# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Audit an exported review without modifying human decisions or frozen test data."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path

from hydra.training.evaluate_corpus import candidate_hash
from hydra.training.evidence_io import write_json
from hydra.training.generation_reliability import wilson
from hydra.training.verified_corpus import sha256


def unique_object(pairs):
    obj={}
    for key,value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON key: {key}")
        obj[key]=value
    return obj


def audit(source: Path, output: Path):
    original_hash=sha256(source)
    review=json.loads(source.read_text(encoding="utf-8-sig"),object_pairs_hook=unique_object)
    dataset=Path("data/external-evaluation-v2/cases.json")
    manifest=json.loads(dataset.with_name("manifest.json").read_text(encoding="utf-8"))
    rows=json.loads(dataset.read_text(encoding="utf-8-sig"))
    by_id={str(row["id"]):row for row in rows}
    excluded={str(i) for group in manifest["duplicate_groups"] for i in group[1:]}
    unique_ids=set(by_id)-excluded
    digest=candidate_hash(Path("models/hydra-instruction-v7/build-manifest.json"))
    answers=json.loads(Path("docs/evidence/external-evaluation-v7.json").read_text(encoding="utf-8"))
    answers_by_id={str(case["id"]):case for case in answers["cases"]}
    errors=[]
    if review.get("artifact_sha256")!=digest or answers.get("artifact_sha256")!=digest:
        errors.append("model binding mismatch")
    if not review.get("dataset_sha256")==sha256(dataset)==manifest["cases_sha256"]==answers.get("dataset_sha256"):
        errors.append("dataset binding mismatch")
    votes=review.get("cases",{})
    for key,vote in votes.items():
        if key not in by_id or vote.get("case_id")!=int(key):
            errors.append(f"invalid case identifier: {key}")
        if vote.get("decision") not in {"correct","incorrect","ambiguous"}:
            errors.append(f"invalid decision: {key}")
        if not str(vote.get("reviewer","")).strip() or vote.get("artifact_sha256")!=digest:
            errors.append(f"invalid reviewer or candidate: {key}")
        if vote.get("decision")=="ambiguous" and not str(vote.get("note","")).strip():
            errors.append(f"ambiguity without explanation: {key}")
        answer=answers_by_id.get(key,{})
        if "output" not in answer or answer.get("error"):
            errors.append(f"no real answer: {key}")
    unique_votes={k:v for k,v in votes.items() if k in unique_ids}
    counts=Counter(v["decision"] for v in unique_votes.values())
    total=len(unique_ids)
    accuracy=counts["correct"]/total
    expected_counters=dict(reviewed=len(votes),unique_cases=total,unique_reviewed=len(unique_votes),
                           correct=sum(v["decision"]=="correct" for v in votes.values()),
                           ambiguous=sum(v["decision"]=="ambiguous" for v in votes.values()),
                           unique_correct=counts["correct"],accuracy_unique_cases=accuracy,
                           accuracy_all_cases=sum(v["decision"]=="correct" for v in votes.values())/len(rows))
    for key,value in expected_counters.items():
        if not isinstance(review.get(key),(int,float)) or not math.isclose(review[key],value,abs_tol=1e-12):
            errors.append(f"saved counter mismatch: {key}")
    objective=[]
    for key in unique_votes:
        if unique_votes[key]["decision"]!="correct" or "JSON" not in by_id[key]["prompt"]:
            continue
        try:
            expected=json.loads(by_id[key]["expected_response"])
            actual=json.loads(answers_by_id[key]["output"])
        except (ValueError,TypeError):
            continue
        if isinstance(expected,dict) and isinstance(actual,dict) and "params" in expected and expected["params"]!=actual.get("params"):
            objective.append(dict(id=int(key),reason="JSON parameter count differs from the requested value",
                                  expected=expected,actual=actual,classification="objective contradiction; human vote retained"))
    if votes.get("113",{}).get("decision")=="correct":
        import ast
        try:
            actual=ast.literal_eval(answers_by_id["113"]["output"])
            expected=json.loads(by_id["113"]["expected_response"])
            if isinstance(actual,list) and Counter(actual)!=Counter(expected):
                objective.append(dict(id=113,reason="sorting changed an input element",expected=expected,actual=actual,
                                      classification="objective contradiction; human vote retained"))
        except (ValueError,SyntaxError,TypeError):
            pass
    report=dict(date="2026-10-01",source=str(source),source_sha256=original_hash,
                artifact_sha256=digest,dataset_sha256=sha256(dataset),structural_errors=errors,
                structurally_valid=not errors,complete_unique_review=set(unique_votes)==unique_ids,
                missing_unique_ids=sorted(map(int,unique_ids-set(unique_votes))),counts=dict(counts),
                unique_cases=total,accuracy_as_submitted=accuracy,wilson95_as_submitted=wilson(counts["correct"],total),
                accuracy_if_all_ambiguous_were_correct=(counts["correct"]+counts["ambiguous"])/total,
                saved_complete=review.get("complete"),duplicate_cases_excluded=len(excluded),
                original_decisions_changed=False,approved=False,objective_contradictions=objective,
                semantic_rechecks=[18,44,59,89,118,179,249,254],rubric_rechecks=[5,13,26,71,132,137,202,226,237,242],
                scope="structural and counter audit plus targeted semantic objections; no automatic adjudication or promotion")
    if sha256(source)!=original_hash:
        raise ValueError("review export changed during audit")
    write_json(output,report)
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("source",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(audit(args.source,args.output),indent=2))
