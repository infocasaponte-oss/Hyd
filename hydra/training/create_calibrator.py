# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Create the versioned Kev calibrator from the saved calibration split only."""
import json
from pathlib import Path

from hydra.training.calibrator import TemperatureCalibrator, fit_temperature


def create(report: Path = Path("data/evaluations/kev-corpus-v3.json"), output: Path = Path("models/kev-calibrator-v3.json")) -> dict:
    data = json.loads(report.read_text(encoding="utf-8"))
    rows = [row for row in data["rows"] if row["split"] == "calibration" and "error" not in row
            and row.get("expected") in row.get("probabilities", {})]
    temperature = fit_temperature(rows)
    dataset = data["dataset_manifest"]["files"]["calibration.jsonl"]
    calibrator = TemperatureCalibrator(temperature)
    calibrator.save(output, calibration_dataset_sha256=dataset["sha256"])
    return {"path": str(output), "temperature": temperature, "rows": len(rows), "dataset": dataset}


if __name__ == "__main__":
    print(json.dumps(create(), indent=2))
