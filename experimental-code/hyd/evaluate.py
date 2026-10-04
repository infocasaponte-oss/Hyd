# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Diagnostic routing evaluation. Never declares a reused corpus independent."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from hydra.core.atomic import write_text_atomic
from hydra.hyd.controller import HydController
from hydra.router.decision_contract import CRITERIA
from hydra.training.decision_metrics import metrics


def evaluate(dataset: Path, model_dir: Path):
    hyd = HydController(model_dir / "model.json", model_dir / "calibration.json")
    raw = dataset.read_bytes()
    measured, latency, accepted = [], [], []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        source = json.loads(line)
        text = source.get("text") or source.get("input", {}).get("query")
        expected = source.get("expected") or source.get("output", {}).get("task_type")
        if not isinstance(text, str) or expected not in CRITERIA:
            raise ValueError("invalid evaluation row")
        started = time.perf_counter()
        answer = hyd.engine.decide(text, {"task": {"type": "choice", "criteria": CRITERIA}})["answers"]["task"]
        latency.append((time.perf_counter() - started) * 1000)
        row = {"expected": expected, "selected": answer["choice"], "probabilities": answer["probabilities"]}
        measured.append(row)
        if not answer["abstained"]:
            accepted.append(row)
    if not measured:
        raise ValueError("empty evaluation")
    return {"format": "hyd-routing-diagnostic/1", "model": hyd.model,
            "model_revision": hyd.engine.ranker.revision,
            "dataset_sha256": hashlib.sha256(raw).hexdigest(), "independent_test": False,
            "authority_enabled": hyd.authority.enabled, "complete": True,
            "metrics_all": metrics(measured), "metrics_accepted": metrics(accepted),
            "selective_coverage": len(accepted) / len(measured),
            "latency_ms": {"p50": float(np.percentile(latency, 50)), "p95": float(np.percentile(latency, 95))},
            "limitations": ["Previously available HYDRA corpus; not untouched promotion evidence.",
                            "CPU latency excludes startup, HTTP and concurrent traffic.",
                            "No live matched Kev comparison; no general decision quality claim."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("data/human-paraphrase-v1.jsonl"))
    parser.add_argument("--model-dir", type=Path, default=Path("config/hyd"))
    parser.add_argument("--out", type=Path, default=Path("docs/evidence/hyd/routing-diagnostic.json"))
    args = parser.parse_args()
    report = evaluate(args.dataset, args.model_dir)
    write_text_atomic(args.out, json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
