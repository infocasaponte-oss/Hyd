# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Recheck pinned Kev on GPU, fit calibration only and keep authority fail-closed."""
import asyncio
import hashlib
import json
from pathlib import Path

from hydra.providers.decision import LocalSystemOneProvider
from hydra.router.decision_authority import DecisionAuthority
from hydra.training.calibrator import TemperatureCalibrator, fit_temperature
from hydra.training.decision_benchmark import cases, questions
from hydra.training.decision_metrics import metrics
from hydra.training.validate_kev import PIN


async def main():
    provider = LocalSystemOneProvider(timeout=30)
    report = {"model": provider.model, "model_revision": PIN, "independent_test": False,
              "complete": False, "approved": False, "rows": []}
    output = Path("docs/evidence/kev-control-2026-09-30.json")
    try:
        cards = (await provider.client.get("/v1/models")).json()["models"]
        card = next(c for c in cards if c["name"] == provider.model)
        if card["run"] != PIN or card["device"] != "cuda":
            raise ValueError("Kev must be the pinned CUDA checkpoint")
        for row in cases():
            if row["split"] == "ood":
                continue
            result = await provider.decide(row["text"], questions())
            answer = result["answers"]["task"]
            report["rows"].append({**row, "probabilities": answer["probabilities"], "selected": answer["choice"]})
            output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        calibration = [r for r in report["rows"] if r["split"] == "calibration"]
        temperature = fit_temperature(calibration)
        calibrator = TemperatureCalibrator(temperature, model_run=PIN)
        calibration_hash = hashlib.sha256(json.dumps(calibration, sort_keys=True).encode()).hexdigest()
        calibrator.save(Path("models/kev-router-calibrator-v4.json"), calibration_dataset_sha256=calibration_hash)
        test = [r for r in report["rows"] if r["split"] == "test"]
        calibrated = [{**r, **calibrator.apply({"probabilities": r["probabilities"]})} for r in test]
        for row in calibrated:
            row["selected"] = row["choice"]
        report.update(metrics(calibrated))
        report.update(complete=True, temperature=temperature, calibration_model_bound=True,
                      limitation="Previously used authored regression panel, not independent production certification")
        report["control_enabled"] = DecisionAuthority.from_evidence(report, provider.model).enabled
        cards = (await provider.client.get("/v1/models")).json()["models"]
        if next(c for c in cards if c["name"] == provider.model)["run"] != PIN:
            raise ValueError("Kev checkpoint changed during evaluation")
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k not in ("rows", "bins")}, indent=2))
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
