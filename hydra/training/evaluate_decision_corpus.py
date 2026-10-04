# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Evaluate the frozen v3 decision corpus against the live Kev endpoint."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from hydra.providers.decision import LocalSystemOneProvider
from hydra.training.calibrator import fit_temperature
from hydra.training.decision_metrics import metrics, select_threshold
from hydra.training.decision_benchmark import questions
from hydra.training.validate_kev import PIN


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def evaluate(root: Path = Path("data/decision-corpus-v3"), output: Path = Path("data/evaluations/kev-corpus-v3.json"), concurrency: int = 2) -> dict:
    if concurrency < 1 or concurrency > 4:
        raise ValueError("concurrency must be 1..4")
    rows = load(root / "calibration.jsonl") + load(root / "test.jsonl")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    provider = LocalSystemOneProvider(timeout=30)
    report = {"status": "RUNNING", "approved": False, "dataset_manifest": manifest,
              "counts": {"calibration": len(load(root / "calibration.jsonl")), "test": len(load(root / "test.jsonl"))},
              "rows": [], "protocol": {"concurrency": concurrency, "model_pin": PIN,
                                        "calibrator_fit_split": "calibration", "test_used_for_fit": False}}
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(concurrency)

    async def one(row: dict) -> dict:
        async with sem:
            started = time.perf_counter()
            result = {"id": row["id"], "split": row["split"], "expected": row["output"]["task_type"],
                      "family": row["family"]}
            try:
                answer = (await provider.decide(row["input"]["query"], questions()))["answers"]["task"]
                result.update(selected=answer["choice"], probabilities=answer["probabilities"],
                              reported_confidence=answer["confidence"])
            except Exception as exc:
                result["error"] = type(exc).__name__
            result["latency_ms"] = (time.perf_counter() - started) * 1000
            return result

    try:
        card = await provider.client.get("/v1/models", timeout=5)
        card.raise_for_status()
        report["server"] = next(c for c in card.json()["models"] if c["name"] == provider.model)
        if report["server"].get("run") != PIN or not report["server"].get("device", "").startswith("cuda"):
            raise ValueError("Kev identity or CUDA check failed")
        for start in range(0, len(rows), concurrency * 8):
            batch = await asyncio.gather(*(one(row) for row in rows[start:start + concurrency * 8]))
            report["rows"].extend(batch)
            async with lock:
                partial = output.with_suffix(".partial.json")
                partial.parent.mkdir(parents=True, exist_ok=True)
                partial.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        calibration = [r for r in report["rows"] if r["split"] == "calibration" and "error" not in r]
        test = [r for r in report["rows"] if r["split"] == "test" and "error" not in r]
        temperature = fit_temperature(calibration)
        report["calibration_raw"] = metrics(calibration)
        report["test_raw"] = metrics(test)
        report["calibrator"] = {"temperature": temperature, "dataset": manifest["files"]["calibration.jsonl"]}
        # Fit is only on calibration. Evaluate transformed probabilities on test.
        from hydra.training.calibrator import TemperatureCalibrator
        calibrator = TemperatureCalibrator(temperature)
        calibrated = []
        for row in test:
            item = dict(row)
            item["probabilities"] = calibrator.probabilities(row["probabilities"])
            item["selected"] = max(item["probabilities"], key=item["probabilities"].get)
            calibrated.append(item)
        threshold = select_threshold(calibration)
        report.update(test_calibrated=metrics(calibrated), threshold=threshold,
                      test_selective_calibrated=metrics(calibrated, threshold),
                      errors=len(rows) - len(calibration) - len(test), status="EVALUATED")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        report.update(status="FAILED", error=type(exc).__name__ + ": " + str(exc))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        raise
    finally:
        await provider.close()
    return report


if __name__ == "__main__":
    result = asyncio.run(evaluate())
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2, ensure_ascii=False))
