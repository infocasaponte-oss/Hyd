# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Backend-independent calibration of COMPLETE labelled candidate scores from vLLM.

Never renormalize a truncated top-logprobs response into full confidence.
Input row: split, expected, candidate_logprobs (every label), logprobs_mode=raw_logprobs.
Scores may be sums of teacher-forced continuation logprobs, not generated-text truth probabilities.
"""
import argparse
import json
import math
from pathlib import Path

from hydra.training.verified_corpus import sha256


def probabilities(scores, temperature=1.0):
    if not scores or not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("finite scores and positive temperature required")
    if any(isinstance(s, bool) or not math.isfinite(float(s)) for s in scores.values()):
        raise ValueError("invalid candidate scores")
    peak = max(float(s) for s in scores.values())
    exp = {k: math.exp((float(s)-peak)/temperature) for k,s in scores.items()}
    total = sum(exp.values())
    return {k:v/total for k,v in exp.items()}


def validate(rows, labels, split):
    if len(set(labels)) != len(labels) or len(labels) < 2 or not rows:
        raise ValueError("nonempty rows and unique candidate labels required")
    for row in rows:
        if row.get("split") != split or row.get("expected") not in labels:
            raise ValueError("wrong partition or label")
        if row.get("logprobs_mode") != "raw_logprobs":
            raise ValueError("raw unprocessed candidate logprobs required")
        if set(row.get("candidate_logprobs", {})) != set(labels):
            raise ValueError("incomplete candidate set; truncated top_logprobs cannot calibrate")
        probabilities(row["candidate_logprobs"])
        if any(float(s) > 0 for s in row["candidate_logprobs"].values()):
            raise ValueError("raw log probabilities cannot be positive")
    if any(not r.get("id") for r in rows) or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("unique example IDs required")


def nll(rows, temperature):
    return -sum(math.log(max(probabilities(r["candidate_logprobs"], temperature)[r["expected"]],1e-300)) for r in rows)/len(rows)


def fit(rows, labels):
    validate(rows, labels, "calibration")
    # Convex NLL in inverse temperature. Bounded golden-section search in beta.
    left, right = .05, 20.0
    ratio = (math.sqrt(5)-1)/2
    for _ in range(100):
        x, y = right-ratio*(right-left), left+ratio*(right-left)
        if nll(rows, 1/x) < nll(rows, 1/y):
            right = y
        else:
            left = x
    return 1/((left+right)/2)


def metrics(rows, temperature):
    ps = [probabilities(r["candidate_logprobs"], temperature) for r in rows]
    correct = [max(p,key=p.get) == r["expected"] for r,p in zip(rows,ps)]
    conf = [max(p.values()) for p in ps]
    ece = 0.
    for i in range(10):
        ix = [j for j,c in enumerate(conf) if i/10 <= c and (c < (i+1)/10 or i == 9)]
        if ix:
            ece += abs(sum(correct[j] for j in ix)-sum(conf[j] for j in ix))/len(rows)
    return dict(nll=nll(rows,temperature), accuracy=sum(correct)/len(rows), ece=ece,
                brier=sum(sum((v-(k==r["expected"]))**2 for k,v in p.items()) for r,p in zip(rows,ps))/len(rows))


def calibrate(path, output, identity, labels, evaluation=None):
    required = {"weights_sha256", "tokenizer_sha256", "backend_version", "quantization"}
    if not required <= identity.keys() or any(not identity[k] for k in required):
        raise ValueError("complete backend/model fingerprint required")
    for key in ("weights_sha256", "tokenizer_sha256"):
        value = identity[key]
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("identity digests must be SHA256")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    temperature = fit(rows, labels)
    report = dict(format="hydra-vllm-candidate-calibrator/1", identity=identity, labels=labels,
                  temperature=temperature, calibration_sha256=sha256(path), approved=False,
                  scope="conditional confidence over the declared candidate set; not arbitrary text correctness",
                  calibration_before=metrics(rows,1), calibration_after=metrics(rows,temperature))
    if evaluation:
        other = [json.loads(line) for line in evaluation.read_text(encoding="utf-8").splitlines()]
        validate(other, labels, "validation")
        if any(not r.get("id") for r in rows+other) or {r["id"] for r in rows} & {r["id"] for r in other}:
            raise ValueError("development and calibration require disjoint IDs")
        report.update(validation_sha256=sha256(evaluation), validation_before=metrics(other,1),
                      validation_after=metrics(other,temperature))
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError("version calibration outputs")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--scores", type=Path, required=True)
    p.add_argument("--identity", type=Path, required=True)
    p.add_argument("--labels", nargs="+", required=True)
    p.add_argument("--validation", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(calibrate(a.scores, a.output, json.loads(a.identity.read_text()), a.labels, a.validation), indent=2))
