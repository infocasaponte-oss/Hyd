# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Finalize an already completed live corpus run without repeating inference."""
import json
from pathlib import Path

from hydra.training.calibrator import TemperatureCalibrator, fit_temperature
from hydra.training.decision_metrics import metrics, select_threshold


def finalize(source: Path, output: Path) -> dict:
    report = json.loads(source.read_text(encoding="utf-8"))
    rows = report["rows"]
    calibration = [r for r in rows if r["split"] == "calibration" and "error" not in r]
    test = [r for r in rows if r["split"] == "test" and "error" not in r]
    temperature = fit_temperature(calibration)
    calibrator = TemperatureCalibrator(temperature)
    calibrated = []
    for row in test:
        item = dict(row)
        item["probabilities"] = calibrator.probabilities(row["probabilities"])
        item["selected"] = max(item["probabilities"], key=item["probabilities"].get)
        calibrated.append(item)
    threshold = select_threshold(calibration)
    report.update(calibration_raw=metrics(calibration), test_raw=metrics(test),
                  calibrator={"temperature": temperature, "dataset": report["dataset_manifest"]["files"]["calibration.jsonl"]},
                  test_calibrated=metrics(calibrated), threshold=threshold,
                  test_selective_calibrated=metrics(calibrated, threshold),
                  errors=len(rows) - len(calibration) - len(test), status="EVALUATED")
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = finalize(Path("data/evaluations/kev-corpus-v3.partial.json"), Path("data/evaluations/kev-corpus-v3.json"))
    print(json.dumps({k: v for k, v in result.items() if k not in {"rows"}}, indent=2, ensure_ascii=False))
