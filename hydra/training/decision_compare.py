# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Paired Hyd/Kev routing comparison against a pinned live local Kev checkpoint."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import numpy as np

from hydra.hyd.continual import ContinualRanker
from hydra.providers.decision import LocalSystemOneProvider
from hydra.router.decision_contract import CRITERIA
from hydra.training.calibrator import TemperatureCalibrator
from hydra.training.decision_active_learning import read_rows, text_label
from hydra.training.decision_candidates import file_sha, group, report_metrics
from hydra.training.evidence_io import write_json


def paired_summary(hyd, kev, seed=42):
    if not hyd or len(hyd) != len(kev) or len({r["id"] for r in hyd}) != len(hyd):
        raise ValueError("complete unique paired rows required")
    by_id = {r["id"]: r for r in kev}
    if len(by_id) != len(kev) or set(by_id) != {r["id"] for r in hyd}:
        raise ValueError("paired ID mismatch")
    groups = {}
    for r in hyd:
        other = by_id[r["id"]]
        if (r["text_sha256"] != other["text_sha256"] or r["expected"] != other["expected"]
                or r["group_id"] != other["group_id"]):
            raise ValueError("paired content/target/group mismatch")
        groups.setdefault(r["group_id"], []).append(
            int(r["selected"] == r["expected"]) - int(other["selected"] == other["expected"]))
    deltas = np.array([np.mean(v) for v in groups.values()])
    rng = np.random.default_rng(seed)
    bootstrap = [float(np.mean(rng.choice(deltas, size=len(deltas), replace=True))) for _ in range(1000)]
    lower, upper = np.quantile(bootstrap, [.025, .975])
    h, k = report_metrics(hyd), report_metrics(kev)
    risk = ("high_risk_review", "security", "privacy", "abstain")
    nonregression = all(h["per_class"][r]["support"] > 0 and
        h["per_class"][r]["recall"] >= k["per_class"][r]["recall"] for r in risk)
    return {"hyd": h, "kev": k, "paired_n": len(hyd), "groups": len(groups),
        "family_mean_delta": float(deltas.mean()), "family_bootstrap_delta_95": [float(lower), float(upper)],
        "population_generalization_certified": False,
        "hyd_superiority_observed": bool(lower > 0 and h["macro_f1_ten_routes"] > k["macro_f1_ten_routes"] and nonregression),
        "critical_recall_nonregression": nonregression}


async def compare(candidate, test, checkpoint, calibration, out, endpoint="http://127.0.0.1:8009"):
    if out.exists():
        raise FileExistsError("new comparison output required")
    report = json.loads((candidate / "report.json").read_text())
    if report["training"]["source_sha256"]["test"] != file_sha(test):
        raise ValueError("candidate/test mismatch")
    for name, expected in report["artifact_sha256"].items():
        if file_sha(candidate / name) != expected:
            raise ValueError("candidate artifacts changed")
    weights = {p.name: file_sha(p) for p in checkpoint.iterdir() if p.is_file() and p.suffix in (".pt", ".safetensors", ".json")}
    if not any(name.endswith((".pt", ".safetensors")) for name in weights):
        raise ValueError("real Kev checkpoint weights required")
    expected_run = str(checkpoint.resolve())
    calibrator = TemperatureCalibrator.load(calibration)
    if calibrator.model_run != expected_run:
        raise ValueError("Kev calibrator bound to another checkpoint")
    provider = LocalSystemOneProvider(endpoint=endpoint, timeout=30)
    result = {"format": "hyd-kev-paired/1", "complete": False, "authority": False, "independent_test": False,
        "candidate_revision": report["model_revision"], "test_sha256": file_sha(test),
        "kev_checkpoint_files": weights, "kev_calibration_sha256": file_sha(calibration),
        "domain": "routing_only", "hyd_rows": [], "kev_rows": []}
    async def check_run():
        response = await provider.client.get("/v1/models")
        response.raise_for_status()
        card = next(c for c in response.json()["models"] if c["name"] == provider.model)
        if card.get("run") != expected_run:
            raise ValueError("Kev server checkpoint differs from pinned run")
    try:
        await check_run()
        model = ContinualRanker.load(candidate / "model.json")
        for row in read_rows(test):
            text, expected = text_label(row)
            start = time.perf_counter()
            probabilities = model.predict_proba(text)
            base = {"id": row["id"], "text_sha256": row["text_sha256"], "group_id": group(row), "expected": expected}
            result["hyd_rows"].append({**base, "probabilities": probabilities,
                "selected": max(probabilities, key=probabilities.get), "elapsed_ms": (time.perf_counter() - start) * 1000})
            await check_run()
            start = time.perf_counter()
            answer = await provider.decide(text, {"task": {"type": "choice", "criteria": CRITERIA}})
            probabilities = calibrator.probabilities(answer["answers"]["task"]["probabilities"])
            await check_run()
            result["kev_rows"].append({**base, "probabilities": probabilities,
                "selected": max(probabilities, key=probabilities.get), "elapsed_ms": (time.perf_counter() - start) * 1000})
        if any(file_sha(checkpoint / name) != expected for name, expected in weights.items()):
            raise ValueError("Kev checkpoint files changed during comparison")
        result["summary"] = paired_summary(result["hyd_rows"], result["kev_rows"])
        result["complete"] = True
        result["promotion_ready"] = False
        result["limitation"] = "development test; new independently reserved human test and approval required"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        raise
    finally:
        write_json(out, result)
        await provider.close()
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate", "test", "checkpoint", "calibration", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--endpoint", default="http://127.0.0.1:8009")
    args = p.parse_args()
    result = asyncio.run(compare(args.candidate, args.test, args.checkpoint, args.calibration, args.out, args.endpoint))
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
