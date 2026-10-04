# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Small, auditable temperature calibrator kept outside Kev's weights."""
from __future__ import annotations

import json
import math
from pathlib import Path


class TemperatureCalibrator:
    def __init__(self, temperature: float = 1.0, version: int = 1, model_run: str | None = None):
        if not math.isfinite(temperature) or temperature <= 0:
            raise ValueError("temperature must be positive")
        self.temperature, self.version = temperature, version
        self.model_run = model_run

    def probabilities(self, probabilities: dict[str, float]) -> dict[str, float]:
        if not probabilities:
            raise ValueError("probabilities required")
        if any(not math.isfinite(float(v)) or not 0 <= float(v) <= 1 for v in probabilities.values()):
            raise ValueError("probabilities must be finite and in [0, 1]")
        if sum(float(v) for v in probabilities.values()) <= 0:
            raise ValueError("probabilities must have positive mass")
        logits = {key: math.log(max(float(value), 1e-12)) / self.temperature
                  for key, value in probabilities.items()}
        peak = max(logits.values())
        weights = {key: math.exp(value - peak) for key, value in logits.items()}
        total = sum(weights.values())
        return {key: value / total for key, value in weights.items()}

    def apply(self, answer: dict) -> dict:
        result = dict(answer)
        result["probabilities"] = self.probabilities(answer["probabilities"])
        result["choice"] = max(result["probabilities"], key=result["probabilities"].get)
        result["confidence"] = max(result["probabilities"].values())
        return result

    def save(self, path: Path, *, calibration_dataset_sha256: str, model_run: str | None = None) -> None:
        path.write_text(json.dumps({"format": "hydra-decision-calibrator/1", "version": self.version,
                                    "temperature": self.temperature,
                                    "calibration_dataset_sha256": calibration_dataset_sha256,
                                    "model_run": model_run or self.model_run}, indent=2),
                        encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "TemperatureCalibrator":
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != "hydra-decision-calibrator/1" or not data.get("calibration_dataset_sha256"):
            raise ValueError("invalid calibrator manifest")
        return cls(float(data["temperature"]), int(data["version"]), data.get("model_run"))


def fit_temperature(rows: list[dict], candidates: tuple[float, ...] = (0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4)) -> float:
    """Choose temperature by NLL on calibration rows only; test rows never enter."""
    usable = [row for row in rows if row.get("expected") in row.get("probabilities", {})]
    if not usable:
        raise ValueError("calibration rows with expected labels and probabilities required")
    best = None
    for temperature in candidates:
        calibrator = TemperatureCalibrator(temperature)
        loss = -sum(math.log(max(calibrator.probabilities(row["probabilities"])[row["expected"]], 1e-12))
                     for row in usable) / len(usable)
        candidate = (loss, temperature)
        if best is None or candidate < best:
            best = candidate
    return best[1]
