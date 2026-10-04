# Copyright (c) 2026 Luis Manuel Cousido Hermida. All rights reserved.
"""Ten-label regression and separately fitted calibration; never certification."""
import argparse
import asyncio
import json
from pathlib import Path

from hydra.providers.decision import LocalSystemOneProvider
from hydra.router.decision_authority import DecisionAuthority
from hydra.training.calibrator import TemperatureCalibrator, fit_temperature
from hydra.training.decision_metrics import metrics
from hydra.training.prepare_kev_hydra_v2 import CRITERIA
from hydra.training.verified_corpus import sha256


async def evaluate(run: Path, output: Path, endpoint="http://127.0.0.1:8009", calibrator_output=None):
    provider = LocalSystemOneProvider(endpoint=endpoint, timeout=30)
    expected_run = str(run.resolve())
    calibration_path = Path("data/decision-corpus-v3/calibration.jsonl")
    test_path = Path("data/human-paraphrase-v1.jsonl")
    train_path = Path("data/kev-hydra-v2/train.jsonl")
    calibration = [{"text": r["input"]["query"], "expected": r["output"]["task_type"], "split": "calibration"}
                   for r in map(json.loads, calibration_path.read_text(encoding="utf-8").splitlines())]
    test = [{**r, "split": "test"} for r in map(json.loads, test_path.read_text(encoding="utf-8").splitlines())]
    trained = {r["state"].strip().casefold() for r in map(json.loads, train_path.read_text(encoding="utf-8").splitlines())}
    if trained & {r["text"].strip().casefold() for r in calibration + test}:
        raise ValueError("Training/evaluation exact text overlap")
    identity = {name: sha256(run / name) for name in ("head.pt", "adapter_model.safetensors", "adapter_config.json")}
    report = {"model": provider.model, "model_revision": expected_run, "checkpoint_files": identity,
              "calibration_sha256": sha256(calibration_path), "test_sha256": sha256(test_path),
              "independent_test": False, "approved": False, "complete": False, "rows": [],
              "limitation": "Known regression prompts and templated calibration; no independent certification"}
    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    async def check_card():
        response = await provider.client.get("/v1/models")
        response.raise_for_status()
        card = next(c for c in response.json()["models"] if c["name"] == provider.model)
        if card["run"] != expected_run or card["device"] != "cuda":
            raise ValueError("Wrong checkpoint or non-CUDA execution")
    try:
        await check_card()
        response = await provider.client.get("/v1/models")
        report["serving_card"] = next(c for c in response.json()["models"] if c["name"] == provider.model)
        for row in calibration + test:
            observed = await provider.decide(row["text"], {"task": {"type": "choice", "criteria": CRITERIA}})
            answer = observed["answers"]["task"]
            report["rows"].append({**row, "selected": answer["choice"], "probabilities": answer["probabilities"]})
            save()
        fitted = fit_temperature([r for r in report["rows"] if r["split"] == "calibration"])
        calibrator = TemperatureCalibrator(fitted, model_run=expected_run)
        calibrator.save(calibrator_output or run / "router-calibrator.json", calibration_dataset_sha256=sha256(calibration_path))
        calibrated = []
        for row in report["rows"]:
            if row["split"] == "test":
                applied = calibrator.apply({"probabilities": row["probabilities"]})
                calibrated.append({**row, **applied, "selected": applied["choice"]})
        report.update(metrics(calibrated))
        report["per_label"] = {label: metrics([r for r in calibrated if r["expected"] == label]) for label in CRITERIA}
        await check_card()
        if identity != {name: sha256(run / name) for name in identity}:
            raise ValueError("Checkpoint changed during evaluation")
        report.update(complete=True, temperature=fitted, calibration_model_bound=True)
        report["control_enabled"] = DecisionAuthority.from_evidence(report, provider.model).enabled
        save()
        print(json.dumps({k: v for k, v in report.items() if k not in ("rows", "bins", "per_label")}, indent=2))
    finally:
        await provider.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8009")
    parser.add_argument("--calibrator-output", type=Path)
    args = parser.parse_args()
    asyncio.run(evaluate(args.run, args.output, args.endpoint, args.calibrator_output))
